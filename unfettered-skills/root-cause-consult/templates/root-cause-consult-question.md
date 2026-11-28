# <Defect class> — root-cause consult

**Answer only at the level of root cause.**

- Do **not** give a repair recipe. Do not tell me which line or function to change, how to make an existing
  test pass, how to make a reviewer's counterexample stop reproducing, or how to get CI green. I will not act
  on that.
- Do not optimise for the currently failing case. If your answer only makes the known counterexamples stop
  reproducing, it is the wrong answer.
- Answer these three: **(1) the root cause** of this recurring class of defect; **(2) what fixing the root
  means** — what must change structurally, in the contract, or in how the work is done; **(3) how I can tell
  the root is fixed rather than the symptom suppressed.**
- If the *whole approach* is the root cause (rather than any part of its implementation), say so plainly and
  say what should replace it.

You have read access to the tree. Use it — read <the readers>, <the helper and its tests>, <the contract
paragraph>, <the plan and evidence>.

## The situation

<One paragraph: what the artifact is, what it is for, who owns the upstream it depends on.>

## What keeps happening

<The successive findings, one bullet each, in shapes not instances: what class each one belonged to.>

## The repair loop, which is part of the problem

Each fix so far has been: take the reviewer's counterexample → change the code until it stops reproducing →
add a case for it → ship. Every round the tree stayed green and the class survived in a new shape. Earlier
consults answered at the level of *how to restructure this function*; their answers are attached. Say where
**each** of them treats symptoms rather than the root — including my own question, when its framing is what
produced the recipe.

## Constraints that cannot be negotiated away

<Ownership boundaries, frozen interfaces, the real requirement that cannot simply be dropped, and the
acceptance mechanics. Naming these stops the answer relocating the problem somewhere you cannot move.>

## Deliverable

Root cause; what fixing the root means; how to know it is fixed. If the answer is uncomfortable (e.g. "this
helper is the wrong shape", "the contract is unenforceable as written", "the information must be captured at
the boundary instead of reconstructed", "the loop itself is the defect"), say it — that is what I am asking
for. Be concrete about which artifact *should* carry the information that is being reconstructed today.
