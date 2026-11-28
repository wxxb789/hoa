# Authoring instruction files for the model reader

SOUL / operating protocol / MEMORY / USER / bot contracts are read by an LLM, not by a human.
Optimize precision and brevity; human readability is not a requirement and must not cost precision.

## Style

- No prose, narrative, throat-clearing or step-by-step teaching. Rules, not essays.
- One reading per rule. Density is fine; ambiguity is not. Mixed languages are fine when shorter.
- **Omit anything the reading agent can obtain by calling a tool** — environment, rosters, ids,
  history, file contents. An agent can look it up; a written copy only rots. This is the single
  biggest source of contract bloat.
- Every rule binds a trigger and an action. A rule with no failure it prevents is deleted, not kept.
- Keep the voice anchors and disambiguating examples that stop a rule being read two ways.

## Layer placement

Sorting key: priority x importance x change-frequency — higher and more stable goes to the more
canonical layer.

| Layer | Carries | Edit needs owner approval |
|---|---|---|
| invariants | rule priority, action gates, interaction constraints, self-evolution loop (compiled into every identity file) | yes |
| identity | stance, voice, role, cwd-independent hard limits | yes |
| rules / protocol | routing, gates, protocols (loads only at its own directory) | yes |
| detail | playbooks, rationale, domain rules, long procedures | no |
| live objects | rosters, models, channels, scheduled jobs — GENERATED from the runtime | no |
| always-on facts | facts and preferences needed in every session | no |
| fact store | dated decisions, environment facts, ids, one-off lookups | no |
| skills | reusable procedures and pitfalls | no |
| runtime config | model / provider / runtime settings | yes |

Allocation test:

1. One canonical owner per rule. A second copy in another layer drifts silently and a later session
   follows whichever copy it loads.
2. Tool-derivable content does not belong in any instruction file except as a pointer to where the
   tool-derived artifact lives.
3. Dated decisions are facts, not rules — put them where they can be queried by date.
4. Procedures are skills; stance, position and limits are the identity file.
5. Change frequency is the tell: if infrastructure changes force a contract edit, that content was a
   live object, not a rule. Fix that systemically rather than adding a rule that says "edit less".

## Extract live objects into a generated inventory

Per-instance identifiers (agent roster, model list, channels, scheduled jobs) are the usual reason a
contract needs constant edits. Generate them from the runtime into one inventory file and have the
contract reference that file.

- **Retarget every checker that asserted those facts *in the contract*.** A drift check of the form
  "every profile is named in the protocol file" false-positives on every item you just moved. Repoint
  it at the inventory, and assert the contract still references the inventory.
- **Add a freshness assertion** so a stale inventory is a finding, not a silent lie: assert every real
  object appears in it, and that it equals a fresh render.
- **Prove freshness read-only.** Import the generator module and compare its `render()` output to the
  on-disk file (strip the timestamp line) instead of regenerating — a health check must not write.
- A checker that hardcodes today's names turns every future roster edit into a permanent red, so match
  case-insensitively and only assert an invariant that survives the change.

## Proving a compression lossless

- Declare one distinctive marker per rule **from the new wording**, then run the coverage checker
  OLD NEW markers — that direction is what proves nothing was dropped.
- A marker lifted from the old sentence reports a phantom loss after a reword; a formatting near-miss
  (backticks, spacing) reports a miss too. Grep the new file for the marker's core phrase before
  trusting a miss.
- Report bytes and non-heading rule lines before/after, and the surviving-rule diff, as the proof.

## De-bloating a monolithic entry file into a router

Trigger: an entry file stops fitting in one read (hundreds of lines / six-figure bytes), so every
activation pays for every rule. Move the depth out — never rewrite the file.

1. **List the target's existing `references/` before naming new files, and reserve those names.** An
   invented topic name can collide with an existing reference covering the same subject, and writing it
   destroys content nobody asked you to touch — put the check in the splitting script so a re-run cannot
   clobber.
2. **Slice by topic, not by line range.** One reference = one topic read on its own; the entry keeps the
   outcome, the must-hold rules and the pointer table.
3. **Move lines verbatim.** A split is a move, not an edit; reworded rules lose their rationale and any
   literal a caller depends on.
4. **Prove the move mechanically before swapping** — reassemble the moved blocks in original order,
   normalize line endings, compare hashes with the original, and print that hash in the report. This is
   stronger than the marker coverage check above, which is for *reworded* rules: a pure move must be
   byte-exact.
5. **Archive the monolith beside the new file**, plus a timestamped copy of whatever the live file held
   at swap time — it is the only source for the next diff.
6. **Verify by activation** (entry + one reference carry every rule for the paths it routes to) and
   report rule counts before/after, not a byte delta alone.

Pitfalls:

- **You are not the only writer.** Curation/consolidation jobs rewrite installed skills on their own
  schedule, so a split computed from an earlier read silently drops whatever they added in between.
  Re-read the live file (hash or mtime) immediately before the swap and merge their content into the
  split instead of overwriting it.
- **An overwritten file is recoverable — restore the bytes, do not re-type them.** The host keeps
  pre-edit content plus a change ledger naming actor/action/path (here: the curator blob store and the
  skill's `.curator_ledger.jsonl`): read the ledger to learn who wrote what and when, then restore the
  exact blob. Re-composing from memory loses formatting and any line the original held.
- **A split that lands only in a materialized profile copy is reverted by the next `--apply`.** Put the
  change in that copy's source (or in `evolvable_skills`) in the same pass, or the next materialize
  restores the monolith.

## Pressure test

Before declaring a restructure done, ask what an adversarial session could exploit: a stale rule still
reachable in an always-loaded file; a vague "put it in the right layer" with no allocation test; an
edited generated artifact drifted from its generator; a gate that cannot fail on a degenerate input.
Fix each by removing the failure mode, not by adding another rule.

The wider rewrite procedure (baseline, one canonical owner, coverage and behavioural evals) lives in
`agent-operating-contract-evolution`.
