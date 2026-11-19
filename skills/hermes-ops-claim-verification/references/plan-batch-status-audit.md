# Auditing how much of an improvement program actually landed

## When to Use

- The owner asks "we got a big review with many suggestions — how much did we apply, and what is left?"
- The owner asks to resume a stalled batch, or suspects a program finished only halfway.
- You found a `BLOCKED-WITH-CHECKPOINT` artifact and need to know whether anything shipped.

The answer is a status table, not a narrative.

## Procedure

1. **Enumerate the review rounds, not just the newest file.** One program usually has several rounds
   (core-system review, per-subsystem review, discussion, plan-generation prompt). List them by size and
   role so you know which file holds the *recommendations* and which holds the *resulting work*.
   `wc -l` the batch first; a 200-line review output is the source of truth, the 10k-line plan files are
   its expansion.
2. **Extract recommendation groups with their IDs.** Reviews are usually numbered (`1.1`, `2.1`, `3.1`…),
   each with "问题 / 根因 / 具体改法 / 预期收益". Keep the ID — the plan titles usually map one-to-one and
   the ID is the only stable join key between the two documents.
3. **Map plan → recommendation by title and scope,** never by plan number order. Plan numbers get
   consumed in batches and generated against a pre-refactor snapshot, so plan-07 may reference paths that
   plan-06 already renamed.
4. **Status comes from the run-log summary's status line**, e.g.
   `grep -m1 -E "^\*\*Status|^Status|^- \*\*Status" run-logs/plan-*.summary.md`.
   Do **not** read status out of `ledger.jsonl`: its events are `start`/`end` with exit codes, so a plan
   that ran and then blocked at a checkpoint still shows `exit: 0`.
5. **Three statuses are real, and they differ:**
   - `DONE` — landed and pushed.
   - `DONE-WITH-CHECKPOINT` — only the safe first stage ran (dry run, preview, manifest). The irreversible
     half was deliberately not executed; the target is untouched.
   - `BLOCKED-WITH-CHECKPOINT` — nothing was written because the plan contradicts a recorded owner
     directive or the repo layout contract.
   A batch that reports "16 plans" with 13/2/1 in those buckets is not "81% done"; it is 13 done and three
   owner decisions outstanding.
6. **Read every checkpoint file for the non-DONE plans.** These hold the real content: numbered conflicts
   (`C1..Cn`) with `path:line` quotes of the contract text, options A/B/C with cost estimates, and one line
   naming exactly what the owner must answer. Relay the options with their costs; do not re-derive them.
7. **Re-verify DONE claims against the current tree.** Cheap probes that have caught stale claims:
   `ls .harness/` for helpers the plan says it created; `cat config/agents.yaml` for the agent count, tiers
   and memory mode; `grep -H "memory:" config/bindings/*.yaml`; `ls roles/` for post-rename directories.
   Absence in the listing is the finding — the summary was true about its commit, not about today.
8. **Look for orphaned sub-items.** A plan covers the load-bearing 60% of a recommendation and quietly
   drops the rest (a staged soft gate, a long-generation wrapper). Read each recommendation's "具体改法"
   line by line against the plan's DONE-WHEN list; report what no plan ever covered as a separate gap row.
9. **Turn each blocked item into a numbered decision.** One question per blocked plan, options with cost
   and risk, recommendation stated. Then put the accepted ones on the board as cards whose body carries
   the chosen option, the contract constraints, and the acceptance commands — the worker never sees the
   chat.

## 10. After the batch lands: one independent audit round

The status table says what shipped; an independent audit says whether it holds. Run exactly one round,
against evidence, and treat the result as a claim set rather than a grade.

- **Bundle**: recommendation IDs, a claims table (`item | claimed status | evidence path`), then raw
  evidence sections — file heads, command output with rc, counts. See the parent skill's §1b for bundle
  hygiene (structure not greps, real record counts, stated population).
- **Fixed verdict vocabulary**: `APPLIED` / `PARTIAL` / `NOT_APPLIED` / `CONTRADICTED` / `UNVERIFIABLE`,
  each with one evidence reference and one line of reason; then a grade, top-3 residual risks, top-3 next
  steps, and a separate list of "claimed but under-evidenced".
- **Forbid redesign.** A reviewer asked to improve the architecture returns opinions instead of verdicts;
  say "judge landing and residual risk, do not re-plan".
- **Re-verify every finding before relaying it**, labelling each `bundle defect` or `real gap` with the
  command that decided. Expect the first round to contain several bundle defects; those are your errors to
  fix, not the auditor's.
- **Close each gap one of two ways**: fix it in the same session with proof, or record it in the receipt as
  an accepted trade-off with the reason. Leaving it only in chat means the next program audit rediscovers it.

## Pitfalls

- **A blocked checkpoint decays into invisible work.** Nobody re-surfaces it because no scheduled job owns
  it; it sits for days while the owner believes the program finished. Write it into the decision queue
  (a `waiting-on-me`-style file) in the same turn you discover it, or it will be found again the same way.
- **Do not count stage-1-only as done.** "Dry run verified" describes the rehearsal, not the vault/repo.
- **Do not re-plan a blocked item before reading its checkpoint.** The conflict is often a policy the
  owner set deliberately (e.g. a retired mechanism); re-landing the original plan re-violates it and the
  next agent will not know why it was stopped.
- **Do not ask the owner to re-decide what a checkpoint already resolved.** They answer with a letter
  (A/B/C); apply that letter exactly, including the "smaller slice" variants, and record the residual
  gap rather than silently widening scope back to the original plan.
- **A "one-line owner nod" buried in an option is still a decision.** When the option text says a syntax
  or schema choice needs approval, state the default you chose in the receipt (reversible), instead of
  leaving it implicit.

## Report shape

- Program inventory: review rounds with paths, plan count, checkpoint count.
- Status table: `recommendation ID | plan | status | evidence path`.
- Blocked rows expanded: conflict quotes, options with cost, the single question.
- Uncovered gaps: sub-items no plan addressed.
- Then the continuation: which cards were dispatched, with ids, owners, and workspaces.
