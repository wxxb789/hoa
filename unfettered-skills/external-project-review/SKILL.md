---
name: external-project-review
version: 0.1.0
description: "Use when reviewing an outside agent project for mechanisms."
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [research, review, harness, comparison, upstream]
---

# External Project Review

Someone else's project arrives as a URL ("看一下这个仓库对我们有什么启发"). The deliverable is a
judgement plus the mechanisms worth adopting — not a summary of its README — and the owner reads the
capability layer before any of the mechanism detail.

## When to use / not

- Reviewing an outside agent harness, tool or repo to decide what to learn or adopt.
- Comparing our harness against a reference implementation.
- Not for: carrying an upstream tree into our repo (`upstream-tree-carry`); auditing our own status
  claims (`report-claim-audit`); proving one external factual claim (`claim-verification`);
  refactoring our own watchdogs and gates (`harness-engineering`).

## Procedure

1. **Snapshot read-only; never run it.** `git clone --depth 50 <url> <scratch>/<name>-inspect`, then
   record commit + date in the artifact. Do not run its installer, setup or CLI: it may want to write
   into the same home that is serving you. Say in the report that nothing was installed or executed.
2. **Verify its own numbers before repeating them.** Stars / last commit / license from the API
   (`/repos/<owner>/<repo>`); counts you compute yourself (`find -name SKILL.md | wc -l`, `wc -l`,
   `ls tests | wc -l`); maturity from the commit log. A README line is a claim, not evidence.
3. **Read its boundary sections first** — the "not for", "does not", terms and pitfalls docs. A
   project that documents what it refuses to do tells you where it sits relative to us; quote its
   stated limits instead of inferring them, and reuse them to argue what *not* to copy.
4. **Map, then judge.** (a) what it is; (b) what it explicitly does not do; (c) its integration points
   against our stack. Then extract mechanisms — for each: the mechanism, **the guard that enforces
   it** (`file:line`), its cost, and the layer here that would carry it (instruction / config / skill /
   script / runtime source = owner-decision scale).
5. **Quantify the scale gap before recommending anything.** LOC, skill and test counts, dependency
   count. What is cheap at their size may be unaffordable at ours; the adoptable mechanisms cluster
   around evidence, vocabulary, gates and budgets — not orchestration scale, which we run on the
   harness primitives we already have.
6. **Report in two layers, capability first.** Layer 1 (chat, plain language): the capability the
   project implements for a user, and which parts of *our* stack it maps onto or would enhance,
   named as our components (skills, plugin hooks, kanban, delegate_task, config, memory). Layer 2
   (artifact): mechanism detail with `file:line`, constants and the project's own stated boundaries at
   `~/claw/tasks/YYYY-MM-DD/<slug>/{analysis.md,mechanics.md}`; chat carries conclusion + evidence
   paths + 2–3 options, and the artifact is linked by path, not pasted.
7. **Mark the epistemic level.** `Fact` = read in source at `file:line`; `Inference` = read in docs
   only; `Judgment` = our comparison. Never present a documented policy as observed behaviour.

## Pitfalls

- **Leading with mechanism detail earns "你说人话".** The owner's first question is what the thing
  *does* and what it changes for us; a jargon-heavy mechanism walk-through answers a question they
  have not asked yet. Answer capability and mapping in their own turn, then offer the depth.
- **The interesting half of a policy is the guard, not the paragraph.** For every mechanism you
  report, find the code that makes violating it impossible (a recursive validator, a gate that
  re-derives a total from the artifact, a closed value set). If there is none, label the claim
  documented-but-unenforced — that distinction is usually the real lesson.
- **Their architecture is not our target.** Copy mechanisms, not scale: a project with six figures of
  tests can afford invariants we cannot service. Report an unaffordable one as such, with the number
  that makes it unaffordable.
- **Nothing here is an install.** Never wire an external project into the runtime as part of a review;
  adoption is a separate, owner-approved change with its own gates and rollback.
- **Check what we already do before proposing adoption.** A mechanism we already implement (a queue
  gate, a review clock, a budget check) is a difference in *enforcement strength*, not a missing
  feature — say which of the two you found, with the evidence from our own tree.

## Follow-on

Mechanisms that land in the instruction layer → `agent-operating-contract-evolution`; gates, watchdogs
and drift checks we then build → `harness-engineering`; a skill we port → `hoa-skill-create`.
