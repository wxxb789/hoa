# Reviewing a user-owned agent contract / control-plane system

Use when the target repo's product is an agent-facing contract system: a kernel file, focused contract
docs, a studies/plans control directory with state machines, receipts, and hash bindings, plus a
`.harness/` of validators. The review goal is usually "it's too complicated / models get blocked / it
wastes tokens" — judge the design, not just the docs.

## Evidence to gather before judging (in order)

1. **Contract surface**: read the kernel + entry contract; count words/files an agent must load before any work. Past ~15k tokens of mandatory contract, weak models lose most of their working window before starting.
2. **Overhead census on a completed "success" object**: count control files/bytes (records, receipts, snapshots, manifests) vs product bytes in the deliverables area. This ratio is the headline number — collect it mechanically (`find`, `wc`, `du`), never by eyeballing.
3. **Run the system's own validator** and cluster ERRORs by rule. Standing error counts measure design debt: hash-drift clusters mean the contract freezes its own bytes. When an exemption registry exists and the errors still stand, grep the validator for the registry read — an unwired "the validator honors this" promise is a dead letter, and the cheap fix is wiring, not re-anchoring.
4. **Read one real object's state history**: count blocked entries, hand-made snapshot files, and receipt/version chains (a simple change producing double-digit versioned receipts is ceremony).
5. **Check executor identities**: which model families actually ran reviews labeled "independent".
6. **Read recent git log**: recurring "repair / refresh hash chain" commits are the system failing its own design.
7. **Check placeholder pollution**: verdict files marked PASS containing `PENDING_*` placeholder values — a fail-closed system that let a fake pass through.
8. **Rebuild canonical accepted/verdict sets from per-domain partitions**: where a system keeps both per-domain acceptance partitions and an aggregated copy, derive the working set from the partitions (explicit id populations) and cross-check the total — quarantined legacy aggregates drift stale and silently under-cover everything built from them.

## Judgment heuristics

- Control-to-product ratio ≥ 1:1 is over-engineering regardless of correctness. Ceremony must be paid for by risk it actually retires.
- Every value the LLM computes, transcribes, or verifies by hand (hashes, IDs, counters) is a token cost AND an error source; transcription slips in fail-closed systems convert directly into blocked states.
- Fail-closed everywhere × an orchestrator that treats `blocked` as terminal/unretryable = single mechanical slip kills the whole run. Complexity must be tiered by consequence, and the weakest intended executor defines the floor: if weak models must run it, they need a path with no complex invariants to violate.
- Hash-freezing the contract's own text into launched objects guarantees drift errors on every later contract edit — by design, not by misuse.
- State machines with 10+ states and 15+ edges are a maze for weak models; most side states can be record fields instead of graph nodes.
- A validator with a large standing error count has no signal value.

## Fix patterns (ranked by leverage)

1. **Script-stamp principle**: the LLM never sees hex. A helper takes intent ("seal this record"), computes hashes, writes atomically, verifies bindings, returns only OK/FAIL+reason. One helper removes both the token cost and the dominant blocked source.
2. **Git as content-addressing**: the repo commit is already a whole-tree content hash. Freeze = record one commit SHA (script-written); change detection = `git diff <commit>..<HEAD> -- <path>`. Retire per-file entry-hash sets and hand-made snapshot directories — they re-implement git worse.
3. **Risk-tiered lanes**: Query (read-only, zero ceremony) / Lite (one-page study record + commit lock; no method profile, no readiness transaction, no lease) / Full (single review + evidence ledger with fields trimmed to what changes decisions) / High-impact (keep the heavy machinery — it is earned here).
4. **State-machine collapse**: e.g. `draft → active → accepted → archived`; demote blocked/paused to fields on the record so an automated doctor can diagnose and clear them.
5. **Doctor script**: on blocked, the first action is a diagnostic/repair script, not model reasoning — weak models cannot be trusted to self-recover from a complex contract.
6. **Fix or legacy-freeze standing validator errors** so the validator regains signal.
7. **Honest independence labels**: same-model-family subagent review = `same-model-family`, or route across families.
8. **Minimal telemetry**: one JSONL row per finished object (tokens, wall time, blocked count, control vs product bytes) — without it the next optimization round is vibes.
9. **Wire exemption registries before re-anchoring**: when objects are already registered in an exemption registry the validator ignores, honor the registry by default — structural checks stay non-exempt, and a `--no-frozen` flag restores raw counts for audit. One wiring change beats re-anchoring bindings for blast radius and keeps the registry honest.

## What NOT to break

- The evidence-lineage conceptual model (claims / anchors / ceilings / as_of / independence) — usually the system's most valuable asset; trim field counts, not concepts.
- Layered ownership (raw sources / distilled knowledge / deliverables split).
- Fail-closed discipline for the genuinely high-impact tier.
- Removing user launch gates in favor of readiness-driven start — that direction reduces friction; take it further rather than reversing it.

## Report shape

Write the full review as an artifact in the task workspace (`<artifacts>/<topic>/`); chat gets TL;DR, per-question answers, a prioritized P0–Pn route with sizes/risks, and a "do not touch" list. Label measured numbers as measured and estimates as estimates. Contract changes inside the target repo follow that repo's own evolution gates — propose, don't apply unilaterally.
