# Multi-model adversarial review of one artifact

Use when a synthesis, plan, design or report needs its reasoning attacked rather than confirmed, and
you want more than one model's opinion. Highest-leverage single step for catching a flawed inference
you have already talked yourself into.

## Recipe

1. **Freeze the artifact under review into one prompt file.** Include the claims verbatim plus the
evidence anchors they rest on, so every model sees the same thing. Vary nothing between models except
the model id — otherwise you cannot tell a model difference from a prompt difference.
2. **Ask for attack, not agreement.** State explicitly: *do not agree politely; attack the reasoning*.
   A neutral "review this" returns praise. Ask for, per claim: is the inference valid, where does it
   overreach, what alternative explanation fits the same evidence, what is the single weakest link,
   what evidence would falsify it, and a confidence rating.
3. **Run each model through the pi-family one-shot** (this skill's §5) rather than hand-rolled HTTP:
   `pi -p --no-tools --no-skills --model <provider>/<id> --thinking high @prompt.md > out.md`
   A long prompt plus long reasoning is exactly the workload that raw HTTP times out on.
4. **Verify each output is complete before trusting it.** A reasoning model can hit the output cap
   mid-answer (`finish_reason=length`) — check the length and the last sentence, and note any truncated
   review as truncated rather than summarising it as if it ended.
5. **Reconcile into a matrix, not a paragraph.** One row per claim, one column per model, cell = that
   model's confidence + its distinct objection. Then list: (a) the attack lines 4+ models share,
   (b) the genuine disagreements, (c) each model's unique contribution.
6. **Act on the consensus, not the average.** Convergence across models on "this inference overreaches"
   is a real signal; a lone high-confidence dissent is worth quoting and, if plausible, testing.

## What this reliably produces

- **Complement treated as a dichotomy** and **mechanism-exists treated as mechanism-dominant** are the
  two attack lines that recur across vendors. Expect them and pre-empt them in the artifact.
- **Causal rankings collapse.** Strong claims of the form "X is the real constraint / the primary gate"
  rarely survive; the durable rewrite is "X is one demonstrated constraint; relative weight untested".
- **A ranking question returns a split, and a split at a position means that position is undecidable.**
  Ask several models to rank the same N candidates and the top slot will often get three different
  answers. Do not mode-vote it into a winner and do not average it: report the matrix with the
  divergence visible and label that position "undecidable from this evidence". If two candidates are
  top-1 in *different* models but separated by 2:1, they differ in evidence *type*, not strength, and
  are not rankable against each other — say so instead of picking one.
- **Audit your own draft claim against the distribution.** Your position may be a minority of one.
  Check it against the model split before publishing, and downgrade it in place if it is — a written
  "my draft placed X first; that was 1/5 and is now downgraded" is more credible than silently
  changing it, and far more credible than shipping the unexamined claim.
- **A last-place rank is not "least important".** Models will rank a candidate last purely because the
  packet contains no evidence about it; require them to state that explicitly ("last = unjudgeable
  here, not unimportant") so the ranking is not read as a judgement of real-world weight.
- **Diminishing but non-zero returns after ~4 models.** Later models stop changing the verdict and
  start contributing analytical *tools* instead (a decomposition, a unit of analysis, a rival
  hypothesis). Value them for those, not for vote-counting.

## Discipline

- The reviews are **author-side inference**, not new evidence. Never fold a review's assertion into the
  artifact as a sourced fact; record it as analysis and keep the original claim's evidence ceiling.
- Keep the raw review outputs as files and cite them; do not paraphrase a model's objection into
  something blander than what it said.
- If a review contradicts a claim, the fix is to narrow the claim, not to add the review as support.
