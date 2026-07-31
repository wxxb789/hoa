---
name: hoa-introspect-distill
description: >-
  Distill approved repeatable work into a reusable skill, or an explicitly opted-in
  rule/config change. Use when asked to "distill this", "turn this workflow into a
  skill", "turn this workflow into a rule", or when handing off repeatable-work
  findings from an hoa-introspect report. Do not use for the work-pattern audit itself
  (use hoa-introspect), raw cross-agent history retrieval (use hoa-agent-retrieve), or
  a one-off task that is not worth reusing.
---

<!-- index: areas=self-management,software-development; targets=runtime-agnostic -->

# hoa-introspect-distill

Turn repeatable work into a small reusable asset, but only after the operator approves
that exact asset. This skill proposes; it never converts an interesting pattern into a
tracked capability by itself.

## Contract

**Input.** Take an `hoa-introspect` repeatable-work finding or a direct user description.
When no history evidence exists, label its basis `user-provided`; do not imply an audit
occurred. Consume only the minimal report shape in [intake schema](references/intake-schema.md).

**Default target.** Create a skill. A rule, `AGENTS.md`, or config edit is opt-in and
requires the same item-specific approval plus the PII gate before any write outside a
skill package.

**Output.** Maintain one state per candidate: `draft`, `ready-for-review`, `approved`,
`rejected`, or `needs-revision`. An approved item yields a creation report containing its
name, location or id, mechanism, review/enablement still needed, and a concise
spec-versus-created diff.

## Workflow

1. **Intake and qualify.** Reuse evidence supplied by `hoa-introspect`; do not re-audit.
   With evidence, prefer stable multi-step work observed at least three times across two
   projects. Reject work already covered, narrowly project-specific work, and one-offs.
   Direct requests may still qualify, but retain the `user-provided` label.
2. **Draft, do not create.** Draft identity, contract, workflow, and basis for each
   qualifying candidate. Rank by expected gain. Five is a ceiling, not a quota: zero
   qualifying candidates is a correct outcome.
3. **Review one candidate at a time.** Present each as `ready-for-review`. Incorporate
   focused feedback, but cap refinement rounds per candidate (default: two); then ask
   whether to approve, reject, or stop. Follow [the approval state machine](references/approval-gate.md).
4. **Gate on an explicit item token.** Resolve candidates with
   `scripts/approval.py:resolve_approval`. Create exactly one asset only for its one
   selected `ready-for-review` id. “Looks good,” an empty token, a repeat/group token,
   or an unknown id is ambiguous: create nothing, halt, and ask which candidate is approved.
5. **Discover or author inline.** Probe for the current runtime’s native skill creator
   and adapt to the interface actually found. Never assume a Claude-only command exists.
   If no compatible creator is found, use [inline authoring](references/inline-authoring.md).
   Never describe a hand-off that did not happen.
6. **Create and verify.** Validate each created `SKILL.md` with
   `python scripts/validate_skill.py <path>`. For an opted-in rule/config/`AGENTS.md`
   target outside this package, first run `python scripts/pii_gate.py <target>`; refusal
   means no write. Do not use `git add -f`.
7. **Report precisely.** State the mechanism (`runtime creator` with its actual name, or
   `inline authoring`), result location/id, remaining manual review/enablement, and every
   deviation from the approved spec. If creation fails, retain the spec and offer the
   shortest retry; do not silently substitute a different target.

## Hard guardrails

- Per-item approval is non-negotiable: one explicit approval creates one asset. On
  ambiguity, halt rather than infer consent.
- Do not pad candidates to five. Stop when all candidates become terminal, the user
  stops, or none qualify.
- Rule/config/`AGENTS.md` output is exceptional: it must be opted in, individually
  approved, and proved untracked or outside every Git worktree before writing.
- Keep personal paths, secrets, session ids, and raw history out of tracked assets and
  chat echoes. Use an untracked artifact location for sensitive reports.
- Sibling composition is soft: if `hoa-introspect` is unavailable, accept a direct basis;
  if `hoa-agent-retrieve` is unavailable, do not attempt raw retrieval here.

## References

- [Intake schema](references/intake-schema.md) — the smallest report/finding contract.
- [Creator discovery](references/skill-creator-discovery.md) — runtime-native probing.
- [Inline authoring](references/inline-authoring.md) — portable fallback.
- [Approval gate](references/approval-gate.md) — candidate state transitions.
