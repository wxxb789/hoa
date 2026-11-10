---
name: spec-convergence
description: >-
  Turn an unclear request into a confirmed spec — a decision tree asked as one numbered round per level,
  every question carrying the repository fact that makes it real, ending in an explicit shared-understanding
  confirmation before anything is written. Use when a request's boundaries, acceptance or test seam are
  still undecided. Not for work whose contract is already written, one-line fixes, or exploring what the
  system does today.
metadata:
  version: "0.1.23"
  areas: "software-development"
  targets: "runtime-agnostic"
  kind: "entry"
  produces: "spec"
---

# Spec Convergence

**Outcome:** a `spec` artifact the operator and the agent both agreed to, with decided boundaries, an
observable acceptance list and one named testing seam.

**Done:** every decision the work depends on was asked and answered by the operator, the concrete answer
was accepted rather than recommended by the agent, and the spec's Open questions section is empty.

**Safe failure:** an unanswered decision stays open. Report what is still open and who must decide it
instead of filling the gap with a plausible default.

## When to Use / Not For

Use when any of these is still undecided:

- What the request includes and, more often, what it excludes.
- What observable result counts as accepted, and at which public boundary it is observed.
- Whether the work should happen at all in the form requested.

Not for work whose contract is already written: read the existing goal file or spec and stop. This
skill does not re-litigate decided questions, plan the implementation, or explore what the system does
today — repository reading here only supplies facts that make a decision concrete.

## Order of Operations

### 1. Facts before questions

Read the repository before asking anything: the project's contract documents, the code the request
touches, its tests, and the configuration that governs it. Mark every fact with the `path` that holds
it, and quote the line or symbol when the exact form matters.

Never ask what the repository already answers; never guess what it can be read. A question is only
valid when its answer is a choice, not a lookup.

### 2. Build the decision tree, not a questionnaire

Every undecided choice is a node. A node's prerequisites are the answers it depends on, so an edge
means "this answer changes what can be decided next". Keep one root per independent concern rather
than flattening the tree into a list: a question whose prerequisite is still open is not answerable
yet, and asking it produces a guessed answer that later answers invalidate.

### 3. Ask one round at a time

A round is the whole **frontier**: every node whose prerequisites are now settled. Send it as one
message, not as a trickle of single questions, and do not pre-ask anything inside the round that
depends on an answer in the same round.

Number the questions `Q1..Qn`. Each carries:

- **Facts:** what the repository showed, with the `path` and the relevant symbol or line.
- **Options:** the genuinely available answers; drop options the facts exclude.
- **Recommended:** one answer, the reason it wins, and the main trade-off losing it costs.

Ask the operator to answer by number and to correct any fact that is wrong. A recommendation is a
question with a suggested answer, not a decision.

### 4. Recompute the frontier after each answer

Add the answer as a settled node, remove its children's prerequisites, and rebuild the frontier before
writing the next round. A recommended answer nobody accepted is still open: never carry a default
forward, and never let a later question assume it.

If the new frontier is empty, go to step 5. If it is unchanged and no new fact unlocks a decision,
stop and say what is blocking instead of asking the same level again.

### 5. Empty frontier means confirm

Present a short shared-understanding summary: the decisions in order, the non-goals, and the acceptance
list. Wait for an explicit confirmation ("确认 / yes"). Silence, a partial answer, or an unaddressed
recommendation is not confirmation, and the spec must not be written before it.

### 6. Write the `spec` artifact

Use these headings only. Do not add a design section, a task list or an implementation sketch.

- **Problem** — the request as now understood, in one short paragraph.
- **Scope** — what the work changes, named at the level the decisions settled.
- **Out of scope** — the non-goals the operator confirmed.
- **Acceptance** — `AC-01`, `AC-02`, … each one observable and checkable by someone who did not
  write the change.
- **Testing seam** — the public boundary where acceptance is judged: the command, endpoint, exported
  symbol, file format or user flow. Name it explicitly and confirm it with the operator. Never a
  private function, and never "we'll see when we write it".
- **Open questions** — must be empty. If one remains, the frontier was not empty; return to step 3.

### 7. Hand off

State which skill continues: `writing-plans` when the agreed spec needs step-level tasks, or a goal
file when the work is an outcome to deliver end to end over a longer window. The spec is the
contract both consume; it is not the plan.

## Rules

- One round per level. Two rounds that reveal no new facts and unlock no node are a stop condition:
  name the missing decision or missing evidence, not another question.
- Never decide on the operator's behalf. A decision made silently is a defect even when the guess
  turns out right.
- Non-goals are part of the spec. An empty "Out of scope" is usually an unfinished answer, not a
  small one.
- The spec is the artifact. Do not restate the plan, the implementation or the repository tour in it.
