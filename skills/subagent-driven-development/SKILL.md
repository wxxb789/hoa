---
name: subagent-driven-development
description: >-
  Execute an implementation plan by dispatching a fresh subagent per task and reviewing each result
  in two stages — spec compliance first, code quality second — then a final integration review.
  Use when a plan already exists, tasks are mostly independent, and quality plus spec fidelity must
  hold between tasks. Not for discovering what to build, and not for one task you can finish in the
  current context.
metadata:
  version: "0.1.18"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
---

# Subagent-Driven Development

## Overview

Execute implementation plans by dispatching a fresh subagent per task with systematic two-stage review.

**Core principle:** Fresh subagent per task + two-stage review (spec then quality) = high quality,
fast iteration.

Method adapted from the public `superpowers` subagent-driven-development flow (MIT); the role names
and the transport-neutral dispatch contract are this port's.

## When to Use

Use this skill when:

- You have an implementation plan (from `writing-plans` or equivalent user requirements)
- Tasks are mostly independent
- Quality and spec compliance are important
- You want automated review between tasks

**vs. manual execution:**

- Fresh context per task (no confusion from accumulated state)
- Automated review process catches issues early
- Consistent quality checks across all tasks
- Children may lack the parent's interactive tools: state every constraint up front rather than
  expecting a child to ask

## Roles

Names in the source material were agent products; they are roles here.

| Role | Owns |
|---|---|
| **controller** | reads the plan once, dispatches, tracks status, enforces review order, integrates |
| **implementer** | one task, full task text, the project's conventions, a report of files/tests/verification |
| **spec reviewer** | the original task text only: every requirement present, nothing extra |
| **quality reviewer** | the touched files: conventions, error handling, names, coverage, edge cases, security |
| **integration reviewer** | the whole change after all tasks: consistency, cross-task seams, full suite |

The controller never implements a task itself. Repair belongs to the implementer or a fresh fix
subagent, so the controller's context stays clean enough to judge.

## The Process

### 1. Read and Parse Plan

Read the plan file. Extract ALL tasks with their full text and context upfront. Record every task in
whatever tracker the work is recorded in, in plan order:

| id | full task text | status |
|---|---|---|
| `task-1` | Create the model with email and password-hash fields | pending |
| `task-2` | Add the password-hashing utility | pending |
| `task-3` | Create the login endpoint | pending |

**Key:** Read the plan ONCE. Extract everything. Don't make subagents read the plan file — provide the
full task text directly in each dispatch.

### 2. Per-Task Workflow

For EACH task in the plan:

#### Step 1: Dispatch Implementer Subagent

Use the harness's fresh-subagent dispatch with complete context. The brief carries:

```
TASK FROM PLAN:
- Create: <exact path>
- Add <class/function> with <fields/signature>
- Use <the library named by the plan>
- Include <debug aid>

FOLLOW THE PROJECT'S TEST-FIRST RULE:
1. Write the failing test in <test path>
2. Run: <test command> (verify FAIL)
3. Write the minimal implementation
4. Run: <test command> (verify PASS)
5. Run: <full suite command> (verify no regressions)
6. Commit: <the plan's commit message>

PROJECT CONTEXT:
- Language/runtime: <version>
- App entry point: <path>
- Existing patterns: <paths>
- Test runner and invocation: <command>
- Dependencies already present: <names>
```

Capabilities are granted explicitly on the dispatch (shell, file read/write, or the adapter's
equivalent). A configuration default is not a capability guarantee: if the child needs to run tests,
say so, and verify from its report that it did.

#### Step 2: Dispatch Spec Compliance Reviewer

After the implementer completes, verify against the original spec, using only the spec:

```
ORIGINAL TASK SPEC:
- <requirements, verbatim from the plan>

CHECK:
- [ ] All requirements from spec implemented?
- [ ] File paths match spec?
- [ ] Function signatures match spec?
- [ ] Behavior matches expected?
- [ ] Nothing extra added (no scope creep)?

OUTPUT: PASS or list of specific spec gaps to fix.
```

**If spec issues found:** Fix gaps, then re-run spec review. Continue only when spec-compliant.

#### Step 3: Dispatch Code Quality Reviewer

After spec compliance passes:

```
FILES TO REVIEW:
- <paths touched by the task>

CHECK:
- [ ] Follows project conventions and style?
- [ ] Proper error handling?
- [ ] Clear variable/function names?
- [ ] Adequate test coverage?
- [ ] No obvious bugs or missed edge cases?
- [ ] No security issues?

OUTPUT FORMAT:
- Critical Issues: [must fix before proceeding]
- Important Issues: [should fix]
- Minor Issues: [optional]
- Verdict: APPROVED or REQUEST_CHANGES
```

**If quality issues found:** Fix issues, re-review. Continue only when approved.

#### Step 4: Mark Complete

Set the task's status in the tracker. Do not start the next task while either review has an open issue.

### 3. Final Review

After ALL tasks are complete, dispatch a final integration reviewer:

```
All tasks from the plan are complete. Review the full implementation:
- Do all components work together?
- Any inconsistencies between tasks?
- All tests passing?
- Ready for merge?
```

### 4. Verify and Commit

Run the acceptance yourself; a child's "tests passed" is a claim.

```bash
# Run full test suite
<full suite command>

# Review all changes
git diff --stat

# Final commit if needed
git add <explicit paths> && git commit -m "<the plan's final message>"
```

## Task Granularity

**Each task = 2–5 minutes of focused work** by default (`SDD_TASK_MINUTES_MIN`,
`SDD_TASK_MINUTES_MAX`).

**Too big:**

- "Implement user authentication system"

**Right size:**

- "Create User model with email and password fields"
- "Add password hashing function"
- "Create login endpoint"
- "Add token generation"
- "Create registration endpoint"

## Red Flags — Never Do These

- Start implementation without a plan
- Skip reviews (spec compliance OR code quality)
- Proceed with unfixed critical/important issues
- Dispatch multiple implementation subagents for tasks that touch the same files
- Make a subagent read the plan file (provide full text in context instead)
- Skip scene-setting context (the subagent needs to understand where the task fits)
- Ignore subagent failures or unresolved ambiguity — fix the context and retry with a fresh subagent
- Accept "close enough" on spec compliance
- Skip review loops (reviewer found issues → implementer fixes → review again)
- Let implementer self-review replace actual review (both are needed)
- **Start code quality review before spec compliance is PASS** (wrong order)
- Move to the next task while either review has open issues

## Handling Issues

### If Requirements Are Ambiguous

- Do **not** expect the subagent to ask the user — delegated children often have no interactive channel
- Put every needed constraint into the delegated context up front
- If a reviewer finds a missing requirement, update the next delegated task with the clarified
  requirement explicitly

### If Reviewer Finds Issues

- Implementer subagent (or a new one) fixes them
- Reviewer reviews again
- Repeat until approved
- Don't skip the re-review

### If Subagent Fails a Task

- Dispatch a new fix subagent with specific instructions about what went wrong
- Don't try to fix manually in the controller session (context pollution)

## Efficiency Notes

**Why fresh subagent per task:**

- Prevents context pollution from accumulated state
- Each subagent gets clean, focused context
- No confusion from prior tasks' code or reasoning

**Why two-stage review:**

- Spec review catches under/over-building early
- Quality review ensures the implementation is well-built
- Catches issues before they compound across tasks

- **Grant capabilities per dispatch.** A global delegation default is documentation, not a guarantee:
  child access is inherited or narrowed by the transport, so state the tools/capabilities the task
  needs on the call. Treat an unreported capability as absent.

## Integration with other skills

### With writing-plans

This skill EXECUTES plans created by the `writing-plans` skill:

1. User requirements → writing-plans → implementation plan
2. Implementation plan → subagent-driven-development → working code

### With test-first development

Implementer subagents should follow the project's test-first rule:

1. Write failing test first
2. Implement minimal code
3. Verify test passes
4. Commit

Include those instructions in every implementer context. If the project has no test-first rule, require
a regression test at the seam the task touches.

### With code review

The two-stage review process IS the code review. For the final integration review, use the review
dimensions the project's own reviewer requires; if it has none, use the quality checklist above plus
"does the whole change satisfy the plan?"

### With systematic-debugging

If a subagent encounters bugs during implementation:

1. Follow `systematic-debugging`
2. Find root cause before fixing
3. Write regression test
4. Resume implementation

## Example Workflow

```
[Read plan: <plan path>]
[Record 5 tasks in the tracker]

--- Task 1: Create User model ---
[Dispatch implementer subagent]
  Implementer: "Should email be unique?"
  Controller: "Yes, email must be unique"      # answered from the plan, then re-dispatched
  Implementer: Implemented, 3/3 tests passing, committed.

[Dispatch spec reviewer]
  Spec reviewer: PASS — all requirements met

[Dispatch quality reviewer]
  Quality reviewer: APPROVED — clean code, good tests

[Mark Task 1 complete]

--- Task 2: Password hashing ---
[Dispatch implementer subagent]
  Implementer: No questions, implemented, 5/5 tests passing.

[Dispatch spec reviewer]
  Spec reviewer: FAIL — missing: password strength validation (spec says "min 8 chars")

[Implementer fixes]
  Implementer: Added validation, 7/7 tests passing.

[Dispatch spec reviewer again]
  Spec reviewer: PASS

[Dispatch quality reviewer]
  Quality reviewer: Important: magic number 8, extract to constant
  Implementer: Extracted MIN_PASSWORD_LENGTH constant
  Quality reviewer: APPROVED

[Mark Task 2 complete]

... (continue for all tasks)

[After all tasks: dispatch final integration reviewer]
[Run full test suite: all passing]
[Done!]
```

## Remember

```
Fresh subagent per task
Two-stage review every time
Spec compliance FIRST
Code quality SECOND
Never skip reviews
Catch issues early
```

## Configuration

| Key | Env | Default |
|---|---|---|
| `dispatch_command` | `SDD_DISPATCH_CMD` | none — the harness's own fresh-subagent command or adapter |
| `task_minutes_min` | `SDD_TASK_MINUTES_MIN` | `2` |
| `task_minutes_max` | `SDD_TASK_MINUTES_MAX` | `5` |
| `child_capabilities` | `SDD_CHILD_CAPABILITIES` | shell, file read/write (pass explicitly per dispatch) |
| `review_order` | `SDD_REVIEW_ORDER` | `spec,quality` — fixed; change only with a documented reason |
| `plan_path` | `SDD_PLAN_PATH` | none — supplied by the caller |

Read `$XDG_CONFIG_HOME/subagent-driven-development/config.yaml` (fallback `~/.config/...`) when
present; a flag or env var overrides the file.

**Quality is not an accident. It's the result of systematic process.**
