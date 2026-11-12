<!-- index: areas=software-development,work-management; targets=repo-only; summary="a skill enters the public catalog only if a stranger on a fresh machine can run it: six gates, hard fails, apply-back invariants"; summary_zh="技能进入公开目录的唯一标准：陌生人在全新机器上能跑通——六道门槛、硬性失败项、回灌不变量" -->

# Generalization rubric — the external-user test

A skill ships here only if a stranger, on a freshly provisioned machine, can run it without
knowing anything about our host. This file is the gate, not advice: run it at nomination time,
not on a schedule.

## Who may enter `skills/` (public catalog)

Only **atomic mechanisms**: standard file/JSON I/O, pure computation, single external call with
declared inputs and outputs. Multi-step orchestration, approval gates, and any workflow that
encodes *our* operating model stay in the owning private repo. A skill that needs a paragraph of
"how we usually do it" to be useful does not belong here.

## Six gates

**G1 — Topology neutral.** No assumption about the caller's directory layout, state files,
frontmatter schema, or ordering of steps. Inputs are explicit paths/streams; nothing is discovered
by convention. *Fail example: "reads `~/.hermes/skills/*/SKILL.md`" — that is our layout, not theirs.*

**G2 — No implicit host coupling.** No assumption of a specific agent framework, MCP server, OS
toolchain, shell, or unpinned external CLI. Every external dependency is named with a version floor
and a check that fails loudly when absent. A "works on my machine" prerequisite list counts as a fail.

**G3 — Configuration is small, typed, and defaulted.** At most **3 required** config keys; every key
has a default that produces a working run. Flag → env → config file → default, in that order.
**A config key may only change an environment scalar** (paths, endpoints, model ids, limits,
credentials handle). If a key changes the step graph or the output contract, that is not
configuration — split the skill.

**G4 — Anti-trigger stated.** The description says when the skill must *not* fire, not just when it
should. A skill without a negative boundary pollutes the caller's context and gets mis-invoked.

**G5 — Runnable by a stranger.** Install and prerequisites documented; one example that runs on a
synthetic input; the example's expected output is committed next to it. Verified by running it in a
container with an **empty `$HOME`** and no pre-existing config; the run log is pasted into the PR.

**G6 — Failure modes declared.** Non-zero exits and their meaning are listed, plus what the skill
leaves behind on failure (and how to clean it). Silent partial success is a fail.

## Hard fails (no discussion)

- Absolute personal paths, private repo/bot/channel/account names, or real identifiers in examples
- Secrets, tokens, or "replace this with your key" sample files
- Success path that only works with our data shape (synthetic example must not be our export)
- Anything whose only validation was "we ran it on the host"

## Review protocol

1. **Nomination is event-driven**: a new skill, a material change, or an explicit proposal. No
   weekly LLM rescoring of an unchanged catalog — model noise produces refactor churn, not quality.
2. **Quarterly deterministic sweep** only: paths, identifiers, config key count, missing anti-trigger,
   missing example. Cheap, no model in the loop.
3. **Roles**: the proposing line writes; the maintainer (Eva) triages and lists gaps, it does not
   author the rewrite; the builder lands the PR; a stateless, one-shot review from a different model
   family scores against this rubric; the owner merges. Self-grading is not allowed.
4. **Scores are reported as gaps, not numbers.** A verdict of "pass" must cite the empty-`$HOME` run.

## Apply-back invariants

Refactored skills return to the live install **only** through the guard:

- materialized copies stay read-only (`0444` files, `0555` dirs)
- before switching the lock: live tree hash == lock `tree_hash`, and == source tree hash
- same-name skill from two sources, or an undeclared local edit, is a **hard stop**
- schema validation and one smoke run must pass before the new lock is written
- rollback = previous lock + previous trees; never a hand-edited copy
