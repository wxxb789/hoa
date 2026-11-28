# Decomposing a delivery pipeline into composable skills

How to take a working but monolithic pipeline skill and split it without losing the guarantees that
made it work. Use when a pipeline skill has grown past what one agent can hold, or when the operator
asks for "several skills, one controller, heavy steps optional".

## The three roles

| Role | Answers | Owns | Never contains |
|---|---|---|---|
| Controller | which skills run, in what order, what must be true between them | stage order, gate invocation, tier resolution | any method, template, or finding taxonomy |
| Mechanism | one verb, one artifact (seal a scope, ask a frontier, run two review axes) | its own script + eval case | references to other mechanisms' internals |
| Domain | repo/stack specifics (build commands, migration rules) | config and profiles | protocol ordering |

A controller that also explains technique will be read as technique and skipped when context is tight.
That is why the controller is a table or a validator subcommand: routing decisions must be
zero-discretion, or routing and method judgement fuse.

## Splitting procedure

1. **List the pipeline's verbs**, one line each (dispatch, verify, simplify, apply fixes, review,
   merge, record). Verbs with a script and a failure mode are mechanism candidates; verbs that only
   sequence other verbs stay in the controller.
2. **Extract the mechanical ones first.** Baseline recording, scope sealing, receipt verification and
   merge gating are pure functions over repository state: they can be built and tested before any
   prose moves, and they are the parts a future session cannot re-derive from memory.
3. **Move protocol text second, by deletion.** After a mechanism exists, delete the corresponding
   paragraphs from the pipeline skill rather than rewriting them. Deletion is reviewable; a rewrite of
   a long instruction file is not.
4. **Name the artifacts and their producers.** Every cross-skill handoff is a file with a declared
   shape (contract file, ledger row, receipt, verdict). One producer per artifact. Validate the graph
   in CI: every consumed artifact must be produced by some skill, no dangling edges. This is the only
   thing that keeps composition from silently becoming duplication.
5. **Decide discovery.** Mechanism skills opt out of automatic triggering; only controllers and domain
   skills compete for routing. With a few dozen skills in the library, adding five more that all match
   the same request destroys trigger accuracy and the routing evals with it.
6. **Re-run the pipeline's own evals**, plus one chain-level dry run. Individual mechanisms passing
   while the chain fails is the normal failure of a decomposition.

## Opt-in tiers: split by cost, not by importance

- **Tier 0 (default, always on):** anything that is a local script over repository state — baseline
  manifest, scope hash, receipt compare, merge gate. Milliseconds, no agent call, no judgement. These
  earn their keep precisely when the operator is in a hurry.
- **Tier 1 (default for the pipeline):** single review axis, bounded fix rounds, ledger row.
- **Tier 2 (opt in):** isolated parallel reviewers, multi-round clarification frontier, advisory
  re-review loops. Cost is measured in agent calls and operator round-trips.

Resolution order for the tier: CLI flag → goal/contract frontmatter → repo profile → default. The more
specific contract wins, and the resolved tier is written into the ledger row so a later reader can tell
what was actually run. Without that record, "we did the strict flow" is unfalsifiable.

## Eval layers a decomposed harness needs

1. **Mechanism (F2P):** each mechanism ships a case that fails before the change and passes after. A
   case that also passes on the old version is vacuous — mark it, do not count it.
2. **Router:** given a request, did the controller pick the right chain and tier? Add distractors.
   This matters more than mechanism evals: one routing error mis-applies the whole chain.
3. **Chain:** two synthetic repos, one run at the cheapest tier and one at the strict tier. Catches
   composition breakage that per-skill tests cannot see.
4. **Artifact contract:** CI check that the produced/consumed graph is complete.

## Anti-patterns

- A "controller" that is a long markdown decision tree — it will be skimmed.
- Mechanism skills that import each other's vocabulary ("as described in seal-scope") — coupling by
  prose instead of by artifact.
- One tier per concern (four toggles) instead of one tier for the whole flow — nobody can predict what
  a run will do.
- Extracting a mechanism without moving its pitfalls: the pipeline keeps the warning, the mechanism
  keeps the bug.
