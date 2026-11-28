---
name: hermes-owner-decision-requests
description: Ask the owner costed option rounds; record the answers.
metadata:
  version: "0.3.2"
  areas: "productivity,software-development"
  targets: "runtime-agnostic"
  summary: "owner-decision rounds: costed options, one form per root, unresolved stays open, answers written to the ledger"
  summary_zh: "向 owner 收集决策：选项标出代价、每个根问题一份表单、未答不算默认、答案落进账本"
  kind: "entry"
  produces: "decision-record"
---

# Owner decision requests

A batch of decisions only the owner can make — the real exam spec, a money ceiling, whose API key is in
play, what private text may reach which vendor, which account boundary is acceptable. The job is to
make each choice decidable in seconds and then leave a record a later reader can challenge.

## Procedure

### 1. Only ask what is genuinely a choice

Read the repo/config first. Current behaviour is a fact, not a decision; absence is a fact too, and
should be named ("no test covers this shape; the key does not exist"). A question whose answer is a
lookup is not a question — it wastes the round and teaches the owner to skim.

**A conflict between the plan and a standing directive is a question, not an implementation detail.**
Before pricing or executing work that assumes a mechanism, grep the operator's own rules for that mechanism:
a deliberately retired or banned one (content hashing, a dependency, an interface frozen by policy, a write
path that must route through a gateway, a daemon replaced by a scheduler) is a decision he already made. The
conflict the plan creates is still his to settle — *override the directive, or change the design* — so raise
it with the directive as the recommended row and quote the path and line that carries it. Executing the plan
silently makes a mechanism he deliberately removed read as a fresh engineering choice, and the resulting
artifact contradicts the very rule that governs the repo.

**That includes questions about his own setup, however unfamiliar it looks to you.** "Which of
our note stores do you mean?", "do you have X configured?", "can I touch that channel?" are
lookups: read the config, the repos, the installed integrations, the running services, then state
the finding as a fact and proceed on it ("no such integration exists here; the vault is <path> —
treating that as the target"), flagging the inference in one clause. Only the owner can answer
*preference, authority or a boundary*; being asked to run discovery he cannot see from the
question costs a round, answers nothing, and reads as handing the work back to him — the reply
is then "you should be doing this for me, not me for you".

**An action the owner already authorized is not a choice either — it is a decision on record, and executing
it IS the delivery.** Before writing options, read the task's own record (its status artifact, the earlier
letter, the directive that named the action). When the word has already been given for a red-zone step and
the pre-flight checks pass, the menu is what stalls it: re-offering it — above all as a row that reads "the
owner does it himself" while you hold the capability — spends a round on a decision he thought he had made,
and he answers it by asking why it is still not done. Authorization given earlier is the opposite of a
timeout default (§5): it needs no second word. The turn's shape is `pre-check → execute → read-back`, with
the exclusions his earlier letter did *not* cover named explicitly. Reserve rounds for choices still open.

**The one time an authorized action waits is when an open question would move its input.** Executing is
the delivery *unless* a still-open question's answer changes the artifact the action consumes — a new
head, a re-cut branch, a rewritten contract — because then running it first spends the expensive half
(the review lane, CI, the long rebuild) on bytes you are about to replace and buys the same run twice.
Check the open set against the action's input before starting, name the pair in one line (`holding the
merge: Q1 = B rewrites the evidence, so the lane would run twice`), do the reversible half that protects
the work (commit locally, save the diff as a patch, push nothing the answer could invalidate — §5), and
keep the expensive step with the letter. A hold with no named question is a stall: the exception is
narrow and must be priced, not asserted.

### 1b. Self-audit rounds: "list what you got wrong and what you are unsure about, then ask"

This request is two artifacts, not one. Deliver them in this order:

1. **Your own errors, first, with the fix that closed each** — one line per error, no hedging, no
   "but it worked out". The owner is calibrating how much of the session's conclusion to trust; a
   report that opens with the uncertainty queue and buries the mistakes reads as if the work were
   first-try correct. Errors already repaired stay in the list (they are the reason the uncertainty
   queue has the shape it has), and irreversible-but-done actions go at the top of it.
2. **The uncertainty queue, ordered by irreversibility** — data/repo deletions first, then production
   actions (restarts, installs, behaviour-changing plugins), then metric/definition questions, then
   conventions. State the count up front (`6 items, in this order`) so the owner knows what he is in for.
3. **Then ask them one at a time.** A self-audit round is a sequence, not a batch: the answer to the
   deletion question changes what the metric question is even about.

Keep "I was wrong" and "please decide" in separate bullets. A single bullet that admits an error and
asks a question makes the owner answer a question he has not finished pricing.

### 2. Write each option with one advantage AND one cost

**A round that prices a design is asked on an independently-reviewed draft, not on your first version.**
When the choices turn on a proposal (a goal refinement, a mechanism split, an interface, a contract change),
the owner may require the draft to be read by a strong model before he sees it — "have <model> read it,
integrate its analysis, then send it to me for approval". Treat that as part of the round rather than as
optional diligence, and keep the order: draft v0 → independent consult recorded verbatim (advice only; shape
in `root-cause-consult`, "a draft design, not a defect") → your integrated revision → the round. Ask the
round on the revision: an option the consult demolished, or one it added, changes what the owner is choosing
between, so sending v0 spends the round on a decision he then has to re-price. The consult's preference is
still not his answer — your recommendation and its cost stay in the rows.

Every option carries `优` and `劣` — the failure mode the choice buys: a looser exposure rule admits
contaminated evidence, a shared counter makes one exhausted provider block the rest, a fixed threshold
becomes a self-deception anchor. An option with only a benefit beside it is a sales pitch, and the
owner will ask for the missing half.

Recommended option first, with the reason it wins and what losing it costs. A recommendation is a
question with a suggested answer, never a decision.

**When the owner asks for "enough options", he means three or four genuinely different mechanisms per
question** — each with its `优`/`劣`, the recommendation first. Two rows plus "leave it as it is" asks him to
price a choice he cannot make; the missing option is usually a different mechanism (the split, the seam, the
deferral) — or, when the acceptance criterion itself sits outside the owner's control (another team
adopting it, a third party using it), the line's abandonment (`drop or replace this line`). A round that
offers only ways to refine a deliverable whose premise each answer dismantles spends its letters on a line
that cannot land, and the owner ends it himself one round later than he had to. Say which layer each option lands in, so picking one is not
also a guess about where it gets written.

**An option must be implementable as written — read the code path that would carry it out before it
goes on the list.** A plausible-sounding lever that the mechanism cannot support (a config marker whose
"essential only" set still contains the very skill being duplicated) is worse than an omitted option:
the owner picks it, and the round costs a second round plus a correction. When the check is cheap
(source read, one grep, a dry run), do it before writing the options; when it is not, write the option
as `needs a probe: <what would prove it>` instead of asserting the outcome.

**An option that names a party — a team, a vendor, a site owner, another service's maintainers — is priced
against that party's real relationship to the work, never against an artifact that merely mentions them.**
A contact-list row, or the record of a team once filing a bug on a neighbouring tool, is not evidence that
it carries the pain the option asserts: the owner picks the letter, the chain turns out never to have
included that party at all, and the round pays a correction plus a re-scoped question. Take the identity
from the owner's own account or from a record that states *this* relationship; when the whole option set
turns on *who*, ask it in the `顺带` fact block first and keep the letters for the actual choice; and when
you do offer an inferred party, write the inference inline (`我只有 <evidence>，未证`) so a wrong guess
costs one message instead of re-scoping the round. This applies with force when the deliverable is
defined by someone else's involvement — "one external team onboards onto this" — because there the party
IS the acceptance criterion, and a fabricated one makes every later question unanswerable.

**Ground the round in the artifacts, and quote what you measured.** When a choice turns on how the real
data looks — how long the sessions actually are, how often the edge case occurs, how many rows the batch
carries — run a cheap read-only summary over the actual stores before writing a row: counts only, never
pulling content, with the command, the sample size and the numbers (`N most recent per source: median /
max / sum`). Cite the code facts an option rests on with path and line, so any row can be challenged
without re-deriving the whole picture, and let the measurement settle the options it makes moot — a size
bound the data never reaches, a shape that turns out not to occur, is not a real choice. A recommendation
argued from intuition gets re-argued the moment the answer meets the data; one carrying its own counts is
decided in the same round. **When the options buy capacity, time or money, the recommended first row is the
zero-cost measurement** — the read-only audit, the baseline run, the inventory — with the spend rows priced as
the follow-ups that measurement would decide. A round that opens with a purchase asks the owner to underwrite a
number neither of you has.

**An option that rewrites a pointer must be checked against the destination, not just the edit.** Open
the path, permission or endpoint the option names and confirm it exists and means what the sentence will
claim — a third-party checkout is not a research-evidence tree, and "point line N at X" is only
implementable if X is that kind of thing. When the check invalidates an option he has ALREADY picked,
open the correction by naming your error in the first line, keep a letter for the literal-but-wrong choice
so his previous answer is still expressible, and re-ask before executing. Silently executing a repaired
version of his letter is how an approval becomes something he never chose.

**Write the net state, not a transform, whenever the transform could collide.** "Swap X for Y" inside a set
that already contains Y describes an impossible edit, and the owner ends up choosing a sentence instead of an
action. Name what the option leaves behind — "drop X → the lane becomes A + B" — so the answer executes
literally.

### 3. One round = one root concern, capped

Number `Q1..Qn`, self-contained: a question that needs another question's context is two questions.
Cap the round at about five. Two independent roots (two goals, two subsystems) are two rounds, so an
answer to one cannot be coloured by the other's wording.

**The owner's attention has its own standing cap, independent of this round's size.** Where the ops contract
fixes a maximum number of decisions parked in front of the owner across *all* surfaces (today's digest, the
blocked/waiting file, picks inside task posts, questions asked in chat), that queue is global, not per-thread:
count what is already in front of him before raising another, hold the overflow as announced titles, and release
one as another clears. And when he asks to be asked one at a time, that is the default shape for every later
batch — one question, take the answer, then the next — not an instruction that expires with the round.

**"What still needs my decision?" mid-workstream is an inventory request, not a question.** Derive the set
from the plan of record plus what landed since it was written (repo head, merged PRs, the task's status
artifact) — never from memory — announce the count and the titles only, then lead with the question whose
answer changes what you do next, saying in one line why it is first. The rest stay parked as announced
titles, so a later answer cannot be coloured by an earlier one.

**Open items owned by another line travel as a labelled annex, not as numbered questions.** When he asks
for "everything I still have to decide", the other lines' open items are in scope for the answer but not
for this round's numbering: give them their own short block (`O1…`) with titles, letters and the ledger
each lands in. Nothing is silently dropped, and every `Q`-number still points at a decision this thread's
owner-of-record executes.

### 4. Deliver one round as ONE form

In chat, the form is `clarify`: the facts and each option's advantage/cost go in the question body, the
pickable labels stay short (`B 40/60 显式 flag`), and the recommended choice is the first row so it
reads as the default.

**Never chain single-question forms.** A one-question form is easy to miss, and a dropped or restarted
turn loses it outright — the owner then has to say "ask me again". **Unless the owner asks to be asked
one at a time** ("一个一个问我"): then send one question per form, in the order you announced —
announce the list of titles first (titles only, not the options), so he sees the shape and how many are
left — and re-send a timed-out one as a form, never as a prose restatement. The per-round cap exists to stop a round from
being scattered; it does not outrank an explicit request for sequencing.

**Never infer a dead widget from old clarify rows — test the channel inside the current round.** Past
`timed_out`/`undelivered` records are minute-level adapter outages, not a verdict on this owner: the same
install answered every form of a later sequenced round. Send the FIRST question as a form and let its own
result decide — `answered` → keep chaining in the announced order; `undelivered` → restate that one
question in prose with the same letters and park the chain (§5); two in a row → diagnose delivery before
asking anything else. A dead-widget conclusion reached from history is how a decidable round gets delivered
in a shape the owner has to reject.

**An owner who answers in chat prose while the form is open HAS answered — read his message against the
open letter and continue in prose.** A one-at-a-time chain that collides with an incoming owner message
comes back `cancelled` with `status: unanswered`: the interrupt dismissed the widget, and his message is
the referent for the letter that form carried. Take it, record it in the answers file, then run the
remaining questions as prose in the durable thread — still one at a time, still each with its `优`/`劣` —
and say in one line that the buttons are abandoned, so he does not wait for pickable rows that are not
coming. Re-sending the widget for a letter he has already answered in words is how the chain loses him.
The outcome field is not the verdict: `cancelled` plus silence is still an open question (§5); `cancelled`
plus a chat message that addresses the question is an answer. Read the content, not the status.

**A repeated sequencing request is proof the batch shape was wrong.** When he has already asked to be
asked one at a time and you answered with one numbered message, he will ask again rather than answer.
Switch to one form per question, in the announced order, and do not re-explain the batch — the repeat is
the request, not a failure to understand.

**Read the sequencing request against the set it names.** "Ask me one by one about those two things" points
at a *set*, not at a chain: resolve the set from evidence (see §6), then send ONE form whose rows are
numbered in the order you announced — the owner answers row by row, and a single round cannot lose its tail
to a timeout. Go back to one form per question as soon as an answer changes what a later question is about
(a dependency chain): there a batched form lets the owner answer a question that no longer exists.
When the round spans more than one
chat message, put the detail in one decision-brief artifact and keep the form short; see
[`references/decision-brief.md`](references/decision-brief.md).

**Pick the surface by where the owner will answer, and check it against the turn's lifetime.** In a work
thread the owner reads and answers in (a task post, a project thread), deliver the round as ONE in-thread
message: the count up front, then each item numbered with its options, each option's `优`/`劣`, and your
recommended letter. A blocking widget holds the turn open while it waits: when it times out, or a restart
lands under it, the owner gets a paused-thread prompt (`/discard` or `/reset`) instead of his options and
the question has to be re-asked — a prose round cannot lose its tail that way. Keep the widget for a single
question he asked to have as pickable rows, and treat "put the options in this thread" (`在这个 thread
里给我选项`) as an instruction to answer in prose **with** the analysis, never as a form whose question body
hides it.

**Read the sequencing request from the LATEST instruction.** A later "ask me everything together"
supersedes an earlier "one at a time": the round then covers the whole open set plus the items you flagged
as uncertain, numbered so every answer is quotable by letter. Say in one line which shape is in force, so a
superseded request is not honoured twice.

### 5. An unanswered round is still open

`unanswered`, `cancelled`, `timed_out` and silence all mean the node is open. Re-send the same round;
never carry the recommended default forward as if it were agreed. If work must proceed, take the
default **and** disclose it in the contract's defaults list with its reversal, so the owner meets it as
a recorded decision rather than discovering it later.

**Whether a timeout takes a default at all depends on the work, not on the timeout.** A question raised
for a later increment, while nothing in flight reads its answer, takes no default: say that the present
shape is simply *still the status quo* — not that the recommended option is now in force — keep the round
open, and send it again as a form at the next fork that actually reads the answer. Taking a default for
symmetry is how an unread question becomes a rule the next session finds recorded and honours.

**Split a timed-out option at the approval boundary before taking any default.** A timeout licenses only the
reversible, gate-free half of what the option described: start that half, and park the half that edits a
contract/config file, touches credentials, restarts a service, or changes shared state until an explicit
letter arrives. A **one-time licence** — an extra audit or fix round, a gate exception, a merge — parks with
those even where executing it would touch nothing at all: what the owner grants there *is* the word, so
silence cannot carry it. "He asked for the round, so silence means yes" is the reasoning that turns a non-answer
into a signature. Report both halves in one line each (what ran, with proof; what is parked, with the letter
or command that unparks it).

**Protect the uncommitted work inside the licensed half.** When the parked half is the *landing* (push, merge,
third audit), the half you are licensed to run usually ends with the fix sitting in a working tree only.
Committing it **locally and pushing nothing** belongs to the licensed half: it is reversible (`git reset`),
changes no shared surface, and stops a stray write, a crash or a restart from destroying work the owner is
still deciding about. Say so in one line (`committed locally <sha>, pushed nowhere`) so the local commit is
not mistaken for the landing, and keep the push with the parked letter — a push moves the very surface that
letter owns.

**When the timeout parks a fork, the licensed half is the artifact the recommended option would dispatch on.**
Pre-build it — the narrowed contract, the option's spec, the distilled option set, the draft the consult
would revise — as a proposal in the task directory, labelled *pre-staged, not dispatched*, with the one word
that releases it. It touches no shared surface (no branch, no contract edit, no dispatch), it is what a
one-letter answer would otherwise cost a whole round to produce, and it keeps the parked item from reading as
dead time. Do not start the work the option describes: that is the parked half.

**A close/archive the owner made conditional is not authorized by a timeout.** When the request is "if
nothing is left, close it", re-check the condition first and let the closing action wait for his word; when
the check fails — work remains — say what remains and keep the thread open. Closing a shared surface against
an unmet condition is worse than a stale open thread, because the remaining work loses the only channel that
reported it.

**In a sequenced round, a timeout pauses the chain, it does not end it.** The letters already executed stay
executed — report each with its proof — and the rest wait: send one message that lists the executed letters and
the pending ones, then stop. Do not answer the next question on the owner's behalf, and do not fold the
remaining questions into a batch because the chain stalled; the round resumes at the open letter when he
writes back.

**Write each answer into the round's answers file the moment it arrives.** A one-at-a-time chain runs for an
hour, with the owner's turns landing between yours: keep `<task>/OWNER-ANSWERS-<date>.md`, one section per
question (the question, the letter, what it authorizes, what it does not), updated as each form returns, and
seed it with the
whole announced set (each question with its options and `优`/`劣`) *before* the first form goes out — when the
chain switches to prose mid-round, or a turn is dropped outright, the options must still exist somewhere — and
fold the finished set into the decision entry once the chain closes. Answers the owner paid for one at a time
must survive an interrupt — his or yours — and be readable without the chat that carried them.

**A partially answered form closes only the letters that came back.** When one form carries several
questions and returns `answered` for some and `unanswered`/`timed_out` for the rest, the settled letters
are decided and the open set is exactly the gap: state which letters are settled in one line, then
re-send only the gap as its own form. Re-sending the whole round re-asks what the owner already paid for
and buries the live question — and when he later says "ask me everything I missed", the missing letter is
the entire referent.

An open decision blocks only the path that depends on it. Keep the independent work moving, and close
every status message with the open question restated in one line plus the letter you would pick — the
owner returning to a long thread reads the last message first, and a question buried mid-paragraph is
the one that gets lost twice.

**A prose restatement is not a re-ask.** When a form times out, the next turn must carry the form again
with the same pickable labels; "reply A or B in the chat" asks the owner to type an option into a thread
he is skimming, and it gets missed a second time — he ends up saying "ask me that again". Re-asking costs
one form; losing it costs a day and a re-import.
**`undelivered` is the one exception, because it is a transport failure rather than an unanswered
question.** When the prompt never reaches the chat (the result carries no owner answer plus a delivery
notice), retrying the same widget is what loses the round: restate that one question in prose with the
same letters, the same costs and the same recommended option, say plainly that the interactive prompt
could not be delivered, and keep the chain parked at that letter. A question the owner could not see is
still open — silence there is not an answer in either direction.

**Two `undelivered` in a row is a channel fault — stop asking and repair delivery first.** Confirm it in
`~/.hermes/logs/gateway.log` (`Prompt send failed: Not connected`, `send_path_degraded`, or
`Failed to edit ... Thread is archived` / code `50083`) instead of concluding the owner is ignoring you.
**Judge the channel by chat delivery, not by the form's own failure.** When ordinary messages keep landing
(the owner replies to the prose around them) while the form returns `undelivered`, only the widget/edit
path is broken: re-ask that question in prose with the same letters and options immediately, and save the
gateway-log hunt for when chat messages themselves stop arriving. Treating a widget-only failure as a
dead channel parks a decidable question behind an investigation the owner never needed.
Discord is the common case: a thread that auto-archived rejects the edit that carries the final text, so
the owner sees a placeholder or nothing at all. Recover by unarchiving the thread
(`PATCH /channels/{thread_id}` with `{"archived": false}` — sending any message unarchives it too) or by
posting the text through the channel's REST helper, which bypasses the edit path entirely — on this host
`python3 ~/.hermes/scripts/discord-forum-post.py comment <thread_id> "<text>"` posts straight to the
thread and prints the created message id, which is the read-back that proves the owner can see it; either
way, re-send the open question in the same message. **An owner who repeats the same status question while you
keep answering is not impatient — he is not receiving.** Diagnose before re-answering, and never read a
repeat as an answer.

**A second consecutive `timed_out` is the owner being away — not a dead channel, and not consent.** The form
is reaching him (chat messages land, no delivery notice), so the fault is timing: the round arrived while he
was inside something else. The first re-send is still the rule (above); what changes on the second timeout is
that a **third** form buys one more blocking wait and holds your own status report behind it — the wrong half
of the turn to spend. Deliver the round once to the durable in-thread surface (the count, each letter with its
options and `优`/`劣`, your recommended letter), say in one line that the interactive prompt expired twice,
execute the timeout-licensed half above, and name each parked item with the letter that unparks it. Then stop
asking until he writes back: the letters are already in the thread, answerable in prose.

**Re-frame the question against what changed, but keep the letters stable.** If independent work moved
while the round was open (the batch already imported with a placeholder, the failing case is now one
record instead of sixty), state the new situation inside the question body and keep each letter pointed
at the same underlying choice, so an answer given from memory still means what it meant.

**An answer that kills the premise of a later announced question re-orders the chain.** When the letter
shows that a question still queued is unanswerable as written — the party it names does not exist, the
artifact it would shape has no subject — say in one line that the order changed, promote the re-framed
question to the lead and say why it is first, and park the dead one as an announced title instead of
asking it into a shape he has to reject. Name with it the upstream artifacts that still assert the dead
premise — the goal line, the plan item, the earlier checklist — as queued for rewrite once the direction
is set, so the next reader does not re-derive a plan from a premise the round just falsified.

**An answer can also retire a letter the owner already gave, and that letter stands rather than
vanishing.** A direction chosen early and a fact learned two questions later collide: he answered the
question as asked, so the letter is not wrong — the line built on it is dead. Record it in the answers
file as `superseded by <later question> — <one clause>`, keep the original row, and re-open the artifacts
that letter had already touched (the plan's workstream, the goal's `next` line, any review scope written
on the retired premise) before writing the replacement. Silently overwriting it leaves the record showing
a direction the round abandoned, and the artifacts the round already edited are exactly the ones nobody
re-reads.

**A question the owner already answered is in force, not open — even while its execution waits.** A letter
whose work is sequenced behind an in-flight increment (a loop to re-enable once the merge lands, a plan item
whose turn has not come) is neither open — he answered — nor moot — nothing ran. List it once in a **settled
block**: the letter, what it authorizes and what it does not, and the condition that releases it (`in force;
executes when <X> lands`). Never re-offer it as an option round: re-asking a settled rule spends his capped
attention (§3) and reads as not listening. The block is what lets the round's letters count only the live
choices — do not pad the count with decisions he already made.

**A round whose default already succeeded is moot — say so in one line, do not re-send it.** When the
recommended option was executed while the form was open and it delivered what it promised (the
measurement now meets the bound, the fix landed and passed), the choices no longer differ in outcome.
State that in the status message, keep the ledger entry as `executed-by-default, never answered` with
its reversal, and carry forward only the questions whose answers still change something — re-sending a
dead question teaches the owner that forms are noise. When he asks to be re-asked what he missed, name
the moot ones explicitly and re-send the live ones.

### 5b. Recovering the open set when the owner asks to be re-asked

"Ask me everything I missed again" is a recovery job, not a re-send job: reconstruct the open set from
evidence before writing a single question. Search, in this order — the whole session's clarify backlog
(as tool results, not as chat prose), each repo's append-only decision ledger, each task's status
artifact, and the tail of every session whose last turn is the agent's (a hanging prose question that
never became a form). Then judge every candidate: unresolved only if the **latest** occurrence is
unanswered, and moot if an artifact shows the default already delivered. Send one form of the live
ones; report the moot ones in one line each with the reason, so the owner sees the audit, not a
resurrection of dead questions. Two open items that turn out to be the same ground are one slot, not two:
name the answer that covers the redundant one and list it in the closed block, so the round spends its letters
on live choices. Recipe, queries and the evidence order →
[`references/recovering-open-decisions.md`](references/recovering-open-decisions.md).

### 6. Record the answer, not just the chat

**Report the executed round one letter per line** — `Q2=D → 退役 home 剥壳保留，报告 …/research-audit.md`.
A misread letter is visible immediately, and the owner does not have to re-derive what each answer
changed.

**A single token carrying several letters (`AAA`) is positional: letter *i* answers announced question *i*.**
Expand it that way in the same turn — one line per letter, naming the question, the option's consequence and
what it does NOT authorize — before executing anything, because a positional read is the one place a wrong
mapping hides inside a token that looks like a blanket approval. Land the expansion in the decision record
(each letter with its scope and its exclusions) rather than keeping it in chat: a record that says only
"owner answered AAA" cannot be challenged later, and the next session re-derives the letters from scratch. When an answer lands in an unexpected layer (a rule he sends to a contract file rather than a
skill), put that in the same line instead of explaining it a turn later.

For each answer capture: the option letter, the consequence in one clause, and how to reverse it. Land
the batch in one increment, in all the places that will be read independently:

- the contract/spec section that states the default in force (so an implementer cannot satisfy the
  letter and miss the consequence);
- the append-only decision ledger, entry flipped to resolved with `Resolution: (owner, <date>)
  option (<letter>) confirmed: …`, keeping the rejected options as the record of what was considered;
- the status index (goal table, roadmap, state column) if a state changed;
- **the artifact a scheduled executor re-reads**, when the approved work belongs to a recurring job — see
  below;
- the owner's waiting-on-me file, when the answer hands work back to him (a bucket, a domain, a credential
  entry point): one dated line with the exact list of what to provide and where the result will be written,
  so the standing nudge surfaces it instead of it dying in the thread's tail.
**Flip the artifact that still reads `OPEN` to the letter, in the same pass.** A status or continuity
artifact whose section header still says *open* while its body carries the answer is what makes the next
reader re-open a settled question; rewrite the header to `answered <letter> (<date>)` and keep the original
option text beneath it as the record of what was chosen between. **A conditional branch inside the chosen
option is not authorized by the letter** — like the red-zone latch above, a fallback ("if X recurs, do Y")
stays parked until its condition is met *and* the owner names it, because the fallback usually lands an
artifact asserting acceptance with debt outstanding. Record it as conditional with the word that releases
it, and say in the executed-round report which step the fallback will need a fresh letter for.

- the same waiting-on-me file in the **closing** direction: an answer that settles an entry **already sitting
  in its 待决 list** moves that line out — checked, under the file's decided section, carrying the letter, the
  decision date and the evidence path (back the file up first, it is a plain only-copy document). A line left
  in the pending list is re-nudged by the next morning sweep, so the owner meets a question he already
  answered and the queue stops being a trustable remainder.

**One writer per repo: a ledger edit cannot land while a live lane owns the checkout.** When the record's
canonical copy is a file in a repo a running job is writing (a conductor's goal stage, another agent's
branch), do not edit it in parallel — put the answers in the round's own task artifact, name the repository
flips as queued, and apply them in one small change the moment the repo frees up. A repo-side flip racing the
lane gets reverted by the lane's next commit; a flip that is never queued is how the next session re-asks a
question the owner already settled. State in the report which items are queued and what unparks them.

**A scheduled executor reads files, not the chat it posts to.** A round that decides a recurring job's
queue only takes effect if the letters land in the artifact that job's own prompt names as its first read —
find it in `~/.hermes/cron/jobs.json` (`cron list` prints no prompt; there is no `cron show`).
Agent-authored messages do not wake another session, so the owner's answers can arrive while the job keeps
advancing its pre-decision queue for hours. Record into the file first, in a dated decision section, keep the
file's `待 owner` section as the live remainder so the next tick inherits the whole set at once, and only then
report the letters in chat. **A letter that authorizes a red-zone step** (a public release, credentials, a third
party's system) is recorded with its latch: the letter fixes the intent, and the record — written in the *executor's* file — names the one explicit word that unparks the irreversible action, so the job asks at that
point instead of reading the preceding letters as blanket approval.

An answer that **contradicts the recommendation** is written with the cost it buys — a per-provider
budget makes the real ceiling the sum; automatic failover is only safe when the authorization scope
matches exactly. Do not smooth an override over in prose.

**Record the negative scope, not just the approval.** When the approved option is a fix or a contract
change someone else will implement, the entry must say what the approval does *not* authorize — the
list stays unexpanded, the live schedule is untouched, the host paths are out of bounds — and the
handoff brief restates the same exclusions. An implementer treats silence as permission and widens the
change to everything the surrounding system could plausibly accept; the exclusion list plus the
acceptance commands (`… --path <target>; echo "exit=$?"`, full suite) is what makes the landed diff
comparable to the decision.

**"Ask me the N things I need to decide" is a pointer, not a question list.** Resolve the referent from
evidence before writing options: the last generated digest (which usually names its own pending
count), the append-only ledger's open section, and any waiting-on-me file — then read the cited source
for each item so every option states a concrete scope. Guessing the set from the topic of the day
produces a form the owner has to correct twice. The raising post is usually priced for its first item
only: the remaining options live in the per-item papers the owning bots wrote into the round's task
directory — read those before writing a single option, because a post that lists five questions and
prices one is exactly why he re-asks.

A docs-only increment that only records decisions still runs the repo's full gate suite: link checks,
secret/source scans and harness self-tests are exactly what a docs edit breaks, and the existing smokes
are the regression control for the merge.

### 7. Execute or dispatch the approvals before you close the turn

Recording is half the job: an approved option usually names an executor. Land the ledger entries, then
either do the small guarded edits yourself (backup → exact-string replace with `assert count == 1` → diff →
read-back) or dispatch the rest to the owning bot.

**Verify each letter against the tree before dispatching its executor — an option already in force is zero
work, and its delivery is the read-back that says so.** A round prices a choice against the state at brief
time, and a commit landing while the forms are open can already implement one of the letters (the guard
narrowed, the flag defaulted, the fix merged). Read the behaviour the letter names at the current head —
grep the guard, run the CLI, `git log -S` the clause — and report it as `Q1 = <letter>; already in force at
<sha>; zero change` instead of opening a lane: an executor told to apply an already-applied option either
no-ops for the price of a round or re-implements the same intent in a second shape, which then diverges
from the reviewed head. The mirror case is a letter that **drops** in-flight work (*not in this increment*),
where the licensed action is to preserve it: save the uncommitted diff as a patch outside the tree
(`git diff > <task>/backups/<work>-<stamp>.patch`), record it in the answers file and the decision ledger,
and name the successor increment that will land it — so a letter that says *not here* does not quietly
become one that says *never*.

- One unit per decision: `agent-dispatch.py start --profile <bot> --prompt <file> --expect <report>
  --unit <unique-name>` in the background with notify; each prompt carries the approved wording verbatim,
  the hard boundaries and non-goals, the report path, the self-proof commands, and "stop and report rather
  than widen". Skeleton: [`templates/decision-execution-prompt.md`](templates/decision-execution-prompt.md).
- Every `--expect` is a report path the run must write (`…/exec/<decision>-report.md`): the dispatcher
  checks existence plus an mtime floor, so a silent no-op fails instead of reading as done.
- Confirm each unit is live (`systemctl --user is-active <unit>`) before reporting the work as delegated,
  then post unit names, the artifact directory and the status command in one message.
- Approvals that cover only a first phase (rule + source, no live deploy; candidate, no promote) keep the
  later phases as separate approvals — the prompt's non-goals list is where that boundary lives, and the
  ledger entry repeats it.
- Read the returned report back against its artifacts before telling the owner it landed; a green dispatch
  verdict is not a verified result.
- **An answered letter is not executed until its executor is running again — do it in the same turn, and
  prove it from state.** When the letter governs a scheduled or series executor (a constant to patch, a unit
  to relaunch, a stage to resume from), the turn that records the answer also patches the constant, restarts
  the unit and arms the waiter; then read the fact back (`systemctl --user is-active <unit>`, the state
  file's next stage/round) instead of trusting the launch call. A turn that ends after recording but before
  relaunching leaves the worst state available: the authorization is spent, the work is dead, and to anyone
  reading later it is indistinguishable from a letter that was never answered — the gap it leaves is
  measured in hours of a run nobody restarted.

**A letter that is shorthand for an artifact is executed literally — including a value the letter never
named.** When the chosen option says *the same text as `<file>`* (a licence, a template, a config block),
copy that file's bytes and verify by hash rather than by eye: the letter approves that text, and a re-typed
paraphrase is a change nobody chose. If the artifact carries a variable the letter did not mention — a
copyright holder, an author name, an account id — do not supply one. Check first whether the repository
already states the position in writing (a README licence paragraph, a contract line): that turns the literal
reading from ambiguous into decidable, and it is cheaper than a round. Then execute the literal reading and
disclose the undefined value in one line (`版权行仍是 <X>，要改成 <Y> 说一句`) instead of inventing it — an
invented holder, name or identity in a legal/attribution field is the one class of guess a later edit cannot
quietly repair.

## Pitfalls

- **A round asked in a thread scoped to another workstream must move out of it.** When the owner says
  "ask me these one by one" inside a thread whose subject is a different line of work, the questions
  belong to other owners (finance, an ops queue, another repo's maintainer). Put the round in its own
  task post — the owner-facing thread — and delegate each item's *preparation* to the owning bot as a
  background run (`hermes -p <profile> chat --query-file <prompt> --oneshot -Q` under
  `systemd-run --user --collect --unit=<name>`, so a gateway restart does not kill it), each writing its
  draft into the round's task directory. The owner answers by letter in the post; the thread that raised
  the question stays on its own subject.
- **Announce the delegation, or the owner concludes nothing is happening.** A headless run is invisible
  in chat: after dispatching, post the unit names, the target artifact paths and the command that shows
  live status, and confirm the runs are actually executing (their per-profile session rows exist with
  recent activity) before reporting the work as delegated.
- **A delegated run still hangs off the gateway — a platform adapter drop kills it mid-write.** Unit exit
  status 0 and an empty log mean nothing; the tell is `Gateway disconnected; turn outcome is unknown`
  (the gateway log shows `Fatal discord adapter error … socket_closed` at that minute) and a missing
  artifact. Resume the printed session id (`--resume <id>` plus a "continue the unfinished artifact,
  do not redo the analysis" prompt) rather than resending the task, and re-check the artifact exists
  before reporting success. `~/.hermes/scripts/agent-dispatch.py` wraps exactly this (dispatch → detect the
  disconnect marker → `--resume` → **artifact existence + mtime floor** → one line `OK`/`FAIL`), and
  reports `FAIL reason=unverified:<what>` when a piece of evidence is missing instead of guessing.
  Known limits that stay documented rather than fixed: give every chain a **unique `--unit`** (never
  reuse a name), treat any `unverified:*` verdict as "check the artifact and the session by hand", and
  note that a crashed chain can still share its log file with a later dispatch that reuses the name.

- Options written only in the chat prose are not answerable when the collection surface is a form —
  the owner cannot click prose. Either both surfaces carry the choices or the form is the only one.
- **A letter authorizes the option as written, not everything the tool does when it runs.** Execute with a dry
  run and read the full target list first: a standing retirement list, a second gateway that shares the id's
  name, another agent's half-finished edit are extra effects the option never described. Surface each as the
  next question instead of letting the executed letter quietly cover them.
- Do not fold two decisions into one question ("count and window") when either could be answered
  differently; split them so a single answer cannot silently decide the other. A FACT the round needs (a
  name, a date, a count, who owns what) is not a decision: ask it in a labelled block beside the question
  (`顺带三个事实`), never as an extra option row, and never let it hold the letter — he answers the letter,
  and the facts ride along in the same message or the next.
- Do not report "all accepted" when the owner answered by number — quote the letters back in one line
  (`Q1 B · Q2 A · Q9 B, override noted`) so a misread is visible before anything is written.
- **A bare token that matches an offered letter IS the answer.** `3A`, `4a`, or the letter alone settles
  that question: record it as `option (<letter>) confirmed` and move to the next announced question. Asking
  him to confirm the letter he just sent reads as re-asking a settled rule.
- **A bare affirmative to your own offer is the go — execute it, do not re-confirm.** `okk`, `ok`, `好的`,
  `可以` landing right after a message that proposed one concrete next action authorizes that action; asking
  again reads as refusing to do settled work. Run the offered step (the usual backup + diff + proof when it
  edits a file) and report what landed. Two limits keep it honest: it covers only what you proposed, not the
  side-ideas floated in the same message, and it cannot unlock a red-zone action — that still needs the word
  naming the action itself.
- **`continue`, silence and a status question are never answers.** None of them contradicts the recommended
  option and none of them agrees to it — they resolve nothing. Answer the ping, keep the open letter visible
  in one line, and spend the turn only on work that does not depend on it. If the default must proceed, label
  it `default taken, never answered` with its reversal: a `continue` read as consent is how a recommended
  option becomes an owner decision it never was.
- A defaulted answer is not a decision. Anything the owner did not answer stays visible as open in the
  ledger with the default and its reversal, or the next session will treat the default as settled.
- Judge a recovered question by its **latest** occurrence, keyed on normalized question text. An earlier
  timed-out form followed by an answered re-send is resolved; scrolling the raw log for `timed_out` and
  re-asking what it finds buries the five live questions under a hundred dead ones.
- Agent-internal sessions (the `local-*` ids that cron and test lanes use) file clarify forms as write
  confirmations to themselves. Their `undelivered` results are not owner questions — filter them out or
  the digest is unreadable.
- **Ask only where someone reads, and check the delivery target before composing the question.** A
  background job whose `deliver` points back at the lane that raised it (`origin`), a cron workspace, or an
  archived thread will file the form into a target nobody is watching: it times out every time and later
  reads in the ledger as "the owner ignored it" — a guaranteed miss wearing an unanswered question's
  clothes. When a question surfaces anywhere but the current conversation, route it to the chat the owner
  actually reads (or re-raise it here) instead of asking into its origin.
- Prove mootness with an artifact, never with the clarify record: the ledger entry's status, the task
  directory's own outcome section, the config value in force, or the merge commit on the remote. "The
  form timed out" says nothing about whether the work happened anyway.
- **Moot it on the object the question names — not on a lookalike, and not by age.** A question is dead
  only when *its* named objects changed: read them. Dismissing "which of the two duplicate weekly jobs do
  we keep" because a similarly named job was retired elsewhere, or because the question is four days old,
  is how a live pair of both-enabled jobs survives a recovery round — the first re-ask the owner makes is
  exactly that item. The re-ask horizon sets ordering and effort, never truth; and when you present a
  "judged moot" block, every line must name what you read, so a wrong dismissal is visible as a missing
  artifact rather than buried in a date.
- Commits ahead of `main` on a local branch do not mean unmerged work: a squash merge leaves the branch
  behind with its subjects already in `main`. Check `gh pr list --state all --search <branch-subject>`
  before reporting a branch as awaiting a merge decision, and report only the genuinely unmerged
  follow-up commits. The mirror case is what misleads a round: a finished task report's own status word
  (`BLOCKED_PENDING_CI`, "not merged", "awaiting CI") is frozen at the moment it was written, so a PR it
  calls pending can be `MERGED` by the time you price a question from it — the report is *why* the item looks
  open, and the live object decides whether it still is. Read the item's own state (`gh pr list --state all`,
  `gh pr view`) before writing its option rows, and when the two disagree, say in the row which artifact
  claimed what.
- A status artifact's header line can be stale against its own body ("one item awaiting approval" above
  a section that records the approval and the diff). Read the body before counting it as an open item,
  and fix the header in the same pass. **Staleness propagates to every reader, so correct the derived texts
  too:** a scheduled notifier that assembles its message from this artifact, and any panel that quotes it,
  keeps re-sending the old reading on every repeat window long after the file itself is right — the alert is
  a claim about the record, and a record nobody re-reads turns an approved item into an open one in the
  owner's inbox. Re-read the notifier's own text (and its next tick) instead of assuming the edit reached its
  audience, and if the artifact's story is now "owner round open", say that in the label rather than leaving a
  hard-coded "waiting for the owner" — a stale label is how an answered question reads as unanswered for a day.
- A widget round that ends in a paused thread is *undelivered*, not unanswered: re-send the whole round as
  one prose message in the same thread with the same letters, options and costs, and do not wait for the
  owner to spot the pause prompt. He will ask "why did this pause?" instead of answering, and the round has
  then cost two turns.
- **A queued surgical edit pins its target's exact text.** Before rewriting a file inside the round's task
  directory, read every pending plan that proposes an exact-string replacement in that file: a guarded
  swap (`assert s.count(old) == 1`) fails closed on its next run once another writer has re-worded that
  line, so the round goes in its own artifact instead of touching a file a queued repair targets.
- **A round's brief goes stale between writing it and asking it.** The paper a round is built from is
  written hours before its forms go out, and other lines keep landing: re-read each question's named
  objects (the file lines, `gh pr view <n>`, the task's closeout) immediately before its form, not once at
  brief time. A question whose premise moved is stated against the new state inside the question body with
  its letters still pointed at the same choice, and the part another line already landed is reported as
  `already executed by <line>, not by your answer` — never folded into your own execution count. Items that
  are fully landed are named moot in one line with the artifact (see the moot rules above), not re-asked.
- **State an incoherent answer back in one line before executing it.** When the letter would produce an
  arrangement the mechanism cannot hold — two stopping rules where one makes the other dead code, a flag the
  code path never reads, a choice that reverses the reasoning printed beside it — write the read-back
  (`-> <letter> means X, which leaves Y unreachable`) and only then execute. That single line is what lets a
  mispriced, misclicked or typo'd letter be corrected for the cost of one message; executing it silently
  spends the correction on edits you then have to undo.
- **A corrected letter is repaired by appending, never by editing the record.** When the owner says he sent
  the wrong letter, keep the original entry intact and append the correction: the letter sent, what it would
  have meant, the letter meant, and the backup/diff/verification of the work that actually landed. A ledger
  whose history has been rewritten cannot show what was authorized when, and the corrected pair is exactly
  what a later reader needs to judge the work.
- **An append is a write: prove it landed.** Put the appender in a file (`assert marker not in text` before,
  `write_text` after, then `grep -c <marker>`), because a composed one-liner whose expression collapses to an
  empty string reports success while appending nothing — and the record then reads as written to every later
  session. Same read-back for the answers file and the ledger entry, before they are reported as recorded.
- **Read the ledger's last entry number immediately before appending, and expect collisions.** The ledger is
  append-only and unlocked, so two lanes writing one log produce duplicate numbers (measured: two entries
  numbered `80` in one session) and a reader who continues from the number that appears last leaves the record
  ambiguous about which `85` is which. Read the physical tail *and* the max — continue from max+1 — and write
  the collision into the status artifact where the next reader looks first, because the duplicate pair is also
  what a later audit re-reads as one decision made twice.
- **A posted round is delivered only if the message object carries it — read the object back, never the
  preview.** The in-thread surface is what the owner answers from, so after posting a round (or its map)
  fetch the message and check its length and its last line: reader/listing helpers cap what they print (a
  forum reader showing at most 1200 characters per message), which makes a complete 1500-character post and a
  genuinely truncated one look identical in the preview. Size the claim in characters, not bytes (CJK ≈ 3
  bytes per code point, so a byte count cannot decide a platform limit counted in characters), and when a
  round exceeds the per-message limit split it at question boundaries rather than trusting that the tail rode
  along — a stored round whose tail never landed reads to every later session as a question the owner ignored.
- **A blocked gate is not unblocked by a different transport.** When the write you owe is refused by a local
  write-guard (a contract, config or instruction file) and this session cannot raise the approval card, the
  forge-side API commit, a second tool, or a paste requested from the owner is *the same write*. Offer it as
  an option row that states what it bypasses (`I commit <file> via the API — that routes around the local
  approval guard`), recommend the owner-authored route first, and never take the bypass without a word that
  names it. Reporting the blocked state with priced options *is* the delivery; achieving the write through
  another door turns the guard into a formality nobody agreed to drop, and the artifact then differs from
  the one the approval was meant to cover. Pair the round with the broken state you found (the pointer whose
  target never landed), since that is what makes it worth its letters.
