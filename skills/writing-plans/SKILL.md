---
name: writing-plans
description: >-
  Write an implementation plan that an agent with zero context for the codebase can execute without
  guessing: exact file paths, complete code, test commands with expected output, and bite-sized
  tasks of 2–5 minutes each. Use before any multi-step feature, complex requirement breakdown, or
  hand-off to a task-per-subagent executor. Not for setting outcomes and ambition (that is goal
  definition) and not for exploring whether the work should happen at all.
metadata:
  version: "0.1.25"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
---

# Writing Implementation Plans

## Overview

Write comprehensive implementation plans assuming the implementer has zero context for the codebase and
questionable taste. Document everything they need: which files to touch, complete code, testing
commands, docs to check, how to verify. Give them bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume the implementer is a skilled developer but knows almost nothing about the toolset or problem
domain. Assume they don't know good test design very well.

**Core principle:** A good plan makes implementation obvious. If someone has to guess, the plan is
incomplete.

Method adapted from the public `superpowers` planning flow (MIT); the plan-shape sections and
hand-off are this port's.

## When to Use

**Always use before:**

- Implementing multi-step features
- Breaking down complex requirements
- Delegating to subagents via `subagent-driven-development`

**Don't skip when:**

- Feature seems simple (assumptions cause bugs)
- You plan to implement it yourself (future you needs guidance)
- Working alone (documentation matters)

## Bite-Sized Task Granularity

**Each task = 2–5 minutes of focused work** by default (`PLAN_TASK_MINUTES_MIN`,
`PLAN_TASK_MINUTES_MAX`).

Every step is one action:

- "Write the failing test" — step
- "Run it to make sure it fails" — step
- "Implement the minimal code to make the test pass" — step
- "Run the tests and make sure they pass" — step
- "Commit" — step

**Too big:**

```markdown
### Task 1: Build authentication system
[50 lines of code across 5 files]
```

**Right size:**

```markdown
### Task 1: Create User model with email field
[10 lines, 1 file]

### Task 2: Add password hash field to User
[8 lines, 1 file]

### Task 3: Create password hashing utility
[15 lines, 1 file]
```

## Plan Document Structure

### Header (Required)

Every plan MUST start with:

```markdown
# [Feature Name] Implementation Plan

> **For the executing agent:** implement this plan task by task using the project's
> task-per-subagent method, if it has one.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

### Task Structure

Each task follows this format:

````markdown
### Task N: [Descriptive Name]

**Objective:** What this task accomplishes (one sentence)

**Files:**
- Create: `exact/path/to/new_file.py`
- Modify: `exact/path/to/existing.py:45-67` (line numbers if known)
- Test: `tests/path/to/test_file.py`

**Step 1: Write failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

**Step 2: Run test to verify failure**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: FAIL — "function not defined"

**Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

**Step 4: Run test to verify pass**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## Writing Process

### Step 1: Understand Requirements

Read and understand:

- Feature requirements
- Design documents or user description
- Acceptance criteria
- Constraints

### Step 2: Explore the Codebase

Use the harness's search, read and shell capabilities to understand the project:

- List the project's source and test layout, and find the file that owns the area you will change.
- Find a similar, already-working feature and read its implementation and tests completely.
- Read the entry point and the configuration that the feature will touch.
- Record the exact test/build commands from the project's own instructions, not from memory.

### Step 3: Design Approach

Decide:

- Architecture pattern
- File organization
- Dependencies needed
- Testing strategy

### Step 4: Write Tasks

Create tasks in order:

1. Setup/infrastructure
2. Core functionality (TDD for each)
3. Edge cases
4. Integration
5. Cleanup/documentation

### Step 5: Add Complete Details

For each task, include:

- **Exact file paths** (not "the config file" but `src/config/settings.py`)
- **Complete code examples** (not "add validation" but the actual code)
- **Exact commands** with expected output
- **Verification steps** that prove the task works

### Step 6: Review the Plan

Check:

- [ ] Tasks are sequential and logical
- [ ] Each task is bite-sized (2–5 min by default)
- [ ] File paths are exact
- [ ] Code examples are complete (copy-pasteable)
- [ ] Commands are exact with expected output
- [ ] No missing context
- [ ] DRY, YAGNI, TDD principles applied

### Step 7: Save the Plan

Write the plan wherever this project records plans — `PLAN_DIR` (default `docs/plans`), file name
pattern `PLAN_FILE_PATTERN` (default `YYYY-MM-DD-<feature>.md`) — then commit it with the project's
commit convention:

```bash
mkdir -p "${PLAN_DIR:-docs/plans}"
# save as "${PLAN_DIR:-docs/plans}/$(date +%Y-%m-%d)-<feature>.md"
git add "${PLAN_DIR:-docs/plans}/"
git commit -m "docs: add implementation plan for <feature>"
```

If the plan is tracked somewhere else (an issue, a board card, a task file), record it there and treat
that surface as authoritative — the plan does not exist twice.

## Principles

### DRY (Don't Repeat Yourself)

**Bad:** Copy-paste validation in 3 places
**Good:** Extract validation function, use everywhere

### YAGNI (You Aren't Gonna Need It)

**Bad:** Add "flexibility" for future requirements
**Good:** Implement only what's needed now

```python
# Bad — YAGNI violation
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
        self.preferences = {}  # Not needed yet!
        self.metadata = {}     # Not needed yet!

# Good — YAGNI
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
```

### TDD (Test-Driven Development)

Every task that produces code should include the full TDD cycle:

1. Write failing test
2. Run to verify failure
3. Write minimal code
4. Run to verify pass

If the project has no test-first rule, still require a regression test at the seam the task touches.

### Frequent Commits

Commit after every task:

```bash
git add [explicit paths]
git commit -m "type: description"
```

## Common Mistakes

### Vague Tasks

**Bad:** "Add authentication"
**Good:** "Create User model with email and password_hash fields"

### Incomplete Code

**Bad:** "Step 1: Add validation function"
**Good:** "Step 1: Add validation function" followed by the complete function code

### Missing Verification

**Bad:** "Step 3: Test it works"
**Good:** "Step 3: Run `pytest tests/test_auth.py -v`, expected: 3 passed"

### Missing File Paths

**Bad:** "Create the model file"
**Good:** "Create: `src/models/user.py`"

## Execution Handoff

After saving the plan, offer the execution approach:

**"Plan complete and saved. Ready to execute using subagent-driven-development — a fresh subagent per
task with two-stage review (spec compliance then code quality). Shall I proceed?"**

When executing, use the `subagent-driven-development` skill:

- Fresh subagent per task with full context
- Spec compliance review after each task
- Code quality review after spec passes
- Proceed only when both reviews approve

## Configuration

| Key | Env | Default |
|---|---|---|
| `plan_dir` | `PLAN_DIR` | `docs/plans` |
| `plan_file_pattern` | `PLAN_FILE_PATTERN` | `YYYY-MM-DD-<feature>.md` |
| `task_minutes_min` | `PLAN_TASK_MINUTES_MIN` | `2` |
| `task_minutes_max` | `PLAN_TASK_MINUTES_MAX` | `5` |
| `test_command` | `PLAN_TEST_CMD` | the project's documented test command |
| `commit_style` | `PLAN_COMMIT_STYLE` | the repo's own commit convention |

Read `$XDG_CONFIG_HOME/writing-plans/config.yaml` (fallback `~/.config/...`) when present; a flag or
env var overrides the file. A plan recorded outside the filesystem (issue, board, task file) is a
project profile choice, not a second source of truth.

## Remember

```
Bite-sized tasks (2-5 min each)
Exact file paths
Complete code (copy-pasteable)
Exact commands with expected output
Verification steps
DRY, YAGNI, TDD
Frequent commits
```

**A good plan makes implementation obvious.**
