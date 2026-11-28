# Instruction-layer placement

How to decide which instruction file a rule belongs in, and how those files are written. The layers,
highest authority first, are ordered by **priority × importance × change frequency**: the more important
and the less often a rule changes, the higher it sits.

| Layer | Holds | Gate |
|---|---|---|
| L0 invariants | rule priority, action gates, ADHD/async policy, self-evolution rules — one source, compiled into every identity file at byte 0 | owner |
| L1 identity (`SOUL.md`) | stance, voice, role, cwd-independent hard limits | owner |
| L2 operating contract (`AGENTS.md`) | routing, gates, protocols — and the placement doctrine itself | owner |
| L3 detail | playbooks, rationale, domain notes the contract points to | none |
| L4 live objects | rosters, model/id tables, schedules — **generated from runtime** | none |
| L5 standing facts | facts and preferences that apply to every session | none |
| L6 fact store | dated decisions, environment facts, ids, one-offs | none |
| L7 skills | reusable procedures and their pitfalls | none |
| L8 config | model, provider, runtime settings | owner |

## Rules

- **Change frequency decides the layer, not importance alone.** A rule corrected weekly must not live in an
  owner-gated file, or every correction blocks on an approval. Symmetrically, a rule that must hold wherever
  the agent runs cannot live in a cwd-scoped project file: sessions started elsewhere load nothing from it and
  say nothing about it.
- **One canonical owner per rule.** A second copy in another layer is drift, and the copies diverge.
- **The ban list belongs *in* the contract.** Write what may not live there (dated decisions → L6;
  rosters/ids/schedules → L4; procedures → L7; runtime settings → L8) into the contract itself, so a later
  session routes correctly without being told again.
- **Laundering.** If the gated layer delegates to an ungated one, the ungated file carries rationale and
  history only: an operative owner rule there can be weakened with no approval, because the gate is on the
  file, not on what the file points at.

## The reader is a model

- Terse, unambiguous, shortest correct form; no prose, no step-by-step teaching, no human-readability tax.
  These files are optimised for an LLM reader, not for a person.
- Omit anything the reader can obtain by calling a tool — file lists, ids, counts, live state. Generate it or
  query it; a hardcoded copy goes stale and silently misleads.

## The generated layer (L4)

Generate rosters, ids and schedules from runtime sources (per-profile config, scheduler state, channel
registry) instead of hand-maintaining them, and guard the generated file with a drift check that fails when
it goes stale or loses a row. A generated file is a *cache* of what a tool can return: if one command can
print the same data, point the contract at the tool and keep the file only for grep/read convenience.

## Proving a restructure

- Declare one distinctive marker per rule before editing; a coverage check that every marker survives is the
  lossless proof. Report the byte delta with the marker count (e.g. 24.9 KB → 13.9 KB, 41/41 markers).
- Back up gated files as a **tarball**: a plain `cp` of a path on the write guard's protected list is refused
  too.
- A marker check proves text survived, not that behaviour did — pair it with behavioural evals before
  trusting a compression (`agent-operating-contract-evolution`).
