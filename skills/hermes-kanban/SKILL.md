---
name: hermes-kanban
description: >-
  Run multi-card work on a persistent board: decompose heterogeneous work, dispatch parallel
  workers, enforce review gates, and recover stuck cards. Use when a task outlives one agent turn
  or needs per-card ownership and routing. Not for a single edit, and not for uniform batch
  fan-out — that wants one resumable runner script.
metadata:
  revision: "1"
  areas: "work-management,software-development"
  targets: "hermes"
  summary: "multi-card board work: decomposition, parallel dispatch, review gates, stuck-card recovery"
  summary_zh: "多卡片看板工作：拆解、并行派发、评审门禁、卡住任务恢复"
  kind: "entry"
---

# Hermes Kanban

## Gates

- Use the board for persistent, heterogeneous work, not a single action or uniform batch fan-out.
- Orchestrate without taking over. Bound each card, name its owner and dependencies, include
  commands and acceptance criteria, and calibrate the criterion on a real sample before dispatch.
- Confirm repo, tenant, account, profile and tool access before claims or writes. Stay in scope;
  parallel writers need distinct files or isolated workspaces. Order same-repo cards with
  explicit `link` dependencies or bound them with `--max-runtime`; do not overlap writes.
  Use `--workspace dir:` for repos with their own publisher; scratch/worktree edits will not reach it.
- Put the guide on disk before creating dependent discovery cards. Assign profiles before dispatch;
  specify the board every time and run only one dispatcher.
- A worker's report is a claim: require artifacts and real command output before review or close.
  Keep discovery read-only apart from its one output per lane; the main thread judges and synthesizes.
- Block early with evidence on missing inputs, permissions or exhausted goal budgets. Preserve
  logs and diffs before reassigning. If an existing artifact passes review, `comment` the evidence
  and `complete --result` with a nonempty result. Fix a miswritten criterion and release the card;
  do not rerun done work.

## Overview

This is the class-level skill for board operations. It merges the former orchestrator and worker
skills into one lifecycle playbook: when to use the board, how to decompose work, how workers
should claim/execute/report, and how to recover stuck work.

The basic worker lifecycle may be auto-injected by runtime guidance. Load this skill when you need
the deeper operational playbook or need to reason across orchestrator and worker roles.

Commands below use `board kanban …` as shorthand for the configured Hermes Kanban CLI.
The subcommands, flags and dispatch behavior assume Hermes.

## When to Use

- The task is larger than one agent turn and benefits from persistent cards.
- Multiple workers/profiles/tools should run concurrently.
- A user asks for status, decomposition, stuck-worker recovery, or board-process debugging.
- You are acting as an orchestrator and must avoid doing the work yourself.
- You are a worker and need concrete summary/metadata/blocking patterns.

Do not use the board for a single simple edit/search/action that the current agent can finish
immediately. Also skip the board for **uniform batch fan-out** — dozens of near-identical runs of one
shape (e.g. the same generation task across every model × variant combination): those want one
resumable runner script (queue, worker pool, per-item receipts, status table) instead of dozens of
cards. The board earns its overhead on *heterogeneous* work that needs per-card routing, ownership,
or review — not on repetition at scale.

## Orchestrator Role

The orchestrator's job is to route work, not secretly complete it.

Anti-temptation rules:
- Do not pick up implementation just because it is interesting.
- Do not hold all context in your private chat; put necessary context on the card.
- Do not assign vague cards like "fix auth". Provide scope, files, commands, acceptance criteria,
  and non-goals.
- Do not spawn more work than you can review.

Decomposition pattern:
1. Identify independent seams: backend/frontend/tests/docs/investigation/review.
2. Create small cards with a single owner and observable finish condition.
3. Include links/paths, commands to run, dependencies, and expected artifacts.
4. Sequence dependent cards explicitly rather than relying on worker intuition.
5. Review outputs and merge/synthesize only verified work.

## Worker Role

Workers should claim only cards they can actually execute with their available tools and workspace.

Good worker loop:
1. Read the card fully, including dependencies and acceptance criteria.
2. Verify workspace/tenant/profile isolation before touching files or external systems.
3. Claim the card and start with a short plan or heartbeat.
4. Execute within the card's scope.
5. Run verification commands and capture real outputs.
6. Return a concise summary with changed files, tests, blockers, and next steps.

Do not:
- Claim cards you created for someone else unless explicitly asked.
- Modify unrelated files while waiting for dependencies.
- Hide uncertainty; block early with a concrete question and evidence.

## Card Content Template

```markdown
# Goal
<one bounded outcome>

# Context
<why this matters; links to docs/issues/PRs>

# Scope
- In: <paths/subsystems/actions>
- Out: <non-goals>

# Acceptance Criteria
- <observable condition>
- <tests or checks>

# Commands
- <exact commands to run>

# Dependencies
- <cards or external decisions>

# Reporting
Return changed files, commands run, output summary, blockers, and confidence.
```

## Summary and Metadata Shapes

A useful worker completion report includes:

```yaml
status: done | blocked | partial | failed
changed_files:
  - path/to/file
commands_run:
  - command: <exact command>
    result: pass | fail | not-run
blockers: []
artifacts:
  - <PR URL, file path, log path, screenshot path>
confidence: high | medium | low
next_steps: []
```

For blockers, include what was tried, the exact missing input/permission, and the smallest question
that would unblock work.

## Heartbeats and Notifications

Worth sending:
- card claimed with ETA/approach
- evidence-gathering found a major scope mismatch
- waiting on a dependency or credential
- long-running tests/builds started or completed
- final completion with artifact handle

Avoid noisy heartbeats that only say "still working" without state change.

## Recovering Stuck Workers

1. Inspect card status, last heartbeat, and claimed worker/profile.
2. Check whether the worker process/session exists and whether its workspace has uncommitted
   changes.
3. Preserve logs and diffs before reassigning.
4. Either unblock with a concrete answer, split the card, or requeue with captured state.
5. Do not duplicate two workers onto the same mutating worktree unless you intentionally fork it.

## Parallel discovery lanes

For read-only evidence fan-out, use distinct lane outputs, one in-repo guide file, a verifier that
depends on all lanes, and main-thread synthesis. Follow
[discovery lanes](references/discovery-lanes.md) for dispatch, review recovery and CLI details.

## Goal-mode cards, swarm, and triage

Choose board-backed root goals for multi-session work; chat `/goal` is single-session.
Use goal-mode cards for iterative acceptance and block on exhaustion or unachievability.
Read [goal mode](references/goal-mode.md) for ownership, limits, auto-decomposition and swarm.

## Verification Checklist

- [ ] Board use is justified by task size/concurrency/persistence.
- [ ] Cards are bounded, testable, and assigned appropriately.
- [ ] Workers have the right workspace/profile/tool access.
- [ ] Reports include artifacts and real verification output.
- [ ] Stuck work has been preserved before reassignment.

## References

- [Board CLI and discovery lanes](references/discovery-lanes.md): shared guide, assignment, dispatch,
  `create --body-file`, `complete --result`, and stuck-review recovery; use these CLI notes for non-discovery cards too.
- [Board pitfalls](references/discovery-lanes.md#pitfalls-across-board-operations): retired
  vocabulary, archiving main-thread takeovers to stop auto-decompose loops, using `unlink` for
  children parked behind a blocked parent, and acceptance calibration.
- [Goal mode](references/goal-mode.md): card budgets, root goals, triage and swarm.
