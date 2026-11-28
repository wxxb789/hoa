# Fanning out a draft matrix (models × variants)

Use when one frozen brief must become many long generations — e.g. every model × skeleton × style
combination — too many for hand-called one-shots. Complements §5 (one routed call) and
`references/multi-model-review.md` (attacking one finished artifact).

## Recipe

1. **Freeze the packet, enumerate the combos.** Build one prompt template from the frozen inputs
   (context + material + the variant definitions); the only per-run variables are the combo's
   dimensions. Resolve the combo list explicitly before launching, and skip combos whose finished
   artifact already exists — re-runs must resume, not restart from zero. When the request names models × variants, the matrix is the **full cross product** — count the grid against the request before launching; a sub-sampled grid is a scope error, not a time saver. Name every artifact by phase-iteration-variant-model (owner pattern: `draft-vXX-skvXX-stvXX-m-<model>.md`) so each file traces to its exact model × variant without opening it.
2. **One resumable runner, not N manual calls.** A script with: combo queue; a worker pool (~6
   concurrent works well for pi-family routes); a **round-robin interleave across models** (mixes
   load and surfaces the first output of every model early); one automatic retry per combo; per-combo
   receipts (prompt file, stderr log, meta JSON); partial/temp outputs in their own subdirectory;
   and a status table (markdown) rewritten on every completion. Log every state change
   (start / done / fail / skip) with byte sizes.
3. **Match the generation mode to the route.** Most routes take the full prompt in one call. Routes
   whose long outputs die mid-stream or truncate at a hard cap run **split mode**: half 1 gets a
   scoped instruction ending with an explicit marker line naming the remaining sections; half 2 is
   an independent continuation prompt with the half-1 text embedded; stitch by stripping the marker,
   then validate. Give split halves their own long per-call timeout — a single-shot budget will kill
   them.
4. **Validate by content, not exit code.** `rc=0` with a truncated or empty file is common; require
   a size floor + structural markers (e.g. the closing section present). A "failed" combo may still
   have a complete artifact at the final path from a partially-validated attempt — **inspect and
   re-validate the on-disk artifact before re-queueing**; salvage before regenerating, which costs
   the full runtime again. Keep partial halves until the combo is confirmed done or doomed — they
   are the salvage material. Chatty models leak progress narration before the real start and a `---`-separated self-check note after the end: take the body from the **last** occurrence of the first expected section heading, cut the trailing note block, then stitch — halves that exited non-zero can still assemble into a clean draft with zero model calls, so accept halves by content (size floor + expected scope), not by return code.
5. **Give throttled tiers their own serial queue.** Free-tier ids rate-limit under concurrency with
   fast empty-output failures and a rate-limit string on stderr. Run those combos serially: one call
   at a time, pacing between calls, backoff-retry cycles (~20 min) on the rate-limit string. Do not
   misdiagnose throttle failures as prompt, schema or route errors. Escalate the route before parking a combo as failed: sibling routes/tiers of the same model id carry independent quotas (SKILL.md pitfall 13). If the model itself is unavailable upstream, do not hot-loop retries — leave a watcher (tiny `Reply with exactly:` probe every ~20 min, capped at a few hours) that fires the leftover writer on the first successful probe and logs every probe as
   evidence. Keep exactly one guard per target — replace, don't stack, when you upgrade it — and probe
   every route the id could return on; tiers recover independently.
6. **Report per combo.** End state = explicit done / skipped / failed lists with sizes; failures
   keep their stderr and partial artifacts as evidence and are named individually in the summary —
   never aggregate failures away. Then hand the batch to the owner for annotation: the next round ships as NEW versioned files (`vXX+1`) with the previous round's originals and receipts kept — iterations are driven by the owner's comments, never silent in-place edits.

## Pitfalls

- Treating `rc` or orchestrator status as the truth about the artifact: verify content.
- Launching every model concurrently with no pacing for throttled tiers.
- Overwriting or deleting half files before the combo is confirmed.
- Building prompts per combo by hand instead of from one template (drift between runs).
- Leaving a model's documented quirks (split mode, credential overrides) in your head instead of in
  in the runner's per-model config.
  - Substituting another model for a failed cell — the model label is the experiment record; watch for
    recovery or report the cell blocked instead.
  - Assuming the stdout capture is the only artifact: tool-enabled CLI agents sometimes self-save
    variant files into the run cwd (scan for stray artifacts after a batch; archive them with a
    provenance note rather than deleting — a self-save can be a richer variant than the stdout
    capture, so review before dismissing).
  - Assuming every receipt reaches git: repos commonly ignore `*.log` — check the ignore rules
    (`git check-ignore -v`) and the staged list before reporting that the evidence landed, and
    redact credential dumps from `.err` receipts first (SKILL.md pitfall 8).
