# The structured citation manifest

§5 of the skill says what to do with an acceptance surface written as prose: make each row a tuple the
gate resolves. This is the shape that worked, in the order the decisions are taken.

## The manifest

- One file per goal, beside its evidence record: `docs/evidence/<goal>-citations.tsv`.
- Tab-separated; a header row names the columns in order; `#` comments and blank lines ignored. Columns:
  `rule_id`, `test`, `package`, `artifact`.
- `artifact` is free text naming where the run's own bytes live (the evidence record's section, the
test's file). It is deliberately **not parsed** — keep the one human-facing column out of the machine's
  path, so a later re-wording of the prose cannot break the check, and the check cannot be satisfied by
  editing prose.

## What the check does, per row

- The named test must **exist** in the named package (grep the package's `_test.go` for `func <test>(`),
  and then it must **run and pass**. Existence alone certifies a name, not a rule — the citation is an
  *executed* pass.
- A test the runner reports as `--- SKIP` is a FAIL. A cited test that is skipped on this platform is not
  the evidence the row claims.
- **Batch the execution per package, not per row.** One `go test -count=1 -v -run '^(<a>|<b>|<c>)$' <pkg>`
  per package, then require each cited test's own `--- PASS` line (and a positive count — a filter that
  matches nothing exits 0, which is §1 one level down). A per-row invocation pays a full compile per
  citation; on a manifest of a few dozen rows that is gate wall-clock nobody can explain later, and it is
  the difference between a step the harness tolerates and one someone eventually widens the timeout for.
- A citation may not point outside what the gate itself tests: refuse a `package` the gate's own target
  list does not cover (resolved, not string-prefixed — §3).

## Required, and the empty set

- Make the step **required** (§10). Then "no manifest anywhere" returns `SKIP`, the promotion rewrites it
  to `FAIL`, and a tree that has lost its acceptance surface cannot read as passing. The manifest's own
  existence is part of what is being gated.
- Therefore **ship a real manifest in the same increment** as the step. A required step and the first
  manifest are one landing, not two — otherwise the step's first appearance is a red on a tree whose only
  fault is that the second half has not landed yet.
- Seed it from a goal whose matrix is already frozen and merged (an archived goal), so the seed is a real
  data set and not a hand-written sample.

## The honest boundary — and how to state it

The manifest can cover only the obligations a **re-runnable** test discharges. Obligations whose evidence
is a one-off external run (a native harness, a paid API, a production read, a live model turn) cannot be
re-executed by a gate, and no amount of design makes them so.

- Do **not** silently omit them. Name the excluded rule ids in the manifest's own header comment, with the
  reason, so the file says what it leaves out. A manifest that is quietly short is a claim stronger than its
  evidence — precisely the defect the mechanism exists to stop, reintroduced by the fix.
- Do **not** close the gap by parsing the prose to discover rule ids. Prose parsing is the fragility being
  replaced; a check that depends on the matrix's wording inherits the loop it was built to end. Completeness
  is asserted by the author at write time, through the excluded-set list.
- Expect the excluded set to be the part that still needs auditing, and say so where the next session will
  read it. That residual is a disclosed gap, not a silent one.

## Deriving the id space when the goal has no frozen matrix

The seed comes from a goal whose matrix was already frozen and merged; the goals that follow usually carry no
matrix at all — their contract is a `Done when` list, a `Bounds` paragraph, and an instruction-file area they
touch. Derive the ids at write time, one number space per source, and name the spaces in the header:

- `D*` — the contract's `Done when` clauses, in order.
- `B*` — its `Bounds` clauses, in order.
- `O*` (or the area's own letter) — every rule of the instruction-file paragraph this increment touches and
  can discharge with a test.

Assign the numbering yourself and freeze it in the file: ids exist so a later round can cite one, and
completeness is the author's claim at write time — never something a parser recovers from the prose. Every
clause gets an id; a clause left unnumbered is the quietly-short manifest one level up.

Choose each row's test by reading the candidate test files and finding the one that actually pins the rule. A
name that reads right and asserts something else is a citation that passes and proves nothing, and a green run
hides it. Keep the clause's own words out of the row: the id, the test, and where it came from.

## Landing it without reddening what already merged

- **Scope the step to the goals that opt in — in data the repo carries** (the goal's own declared surface),
  never through an exemption list of older goal ids. An exemption list is a second exclusion mechanism beside
  the manifest's own header, and it is the half nobody updates.
- **Enforce the per-goal obligation where the goal is still open.** Goals that predate the mechanism keep
  their landed record; the requirement reaches new work through the driver, which refuses to run or accept a
  goal whose manifest is missing (a block naming the path), rather than through the gate failing every tree
  that has none.
- **The first consumer is usually a pull request already open.** Author its manifest as a data-only change on
  that goal's branch — the manifest file and nothing else — so the acceptance swap is reviewable as one file,
  and the mechanism increment keeps its own PR.

## Selftests

- One case per rule above, each shown to **fail when its rule is broken**: wrong header; a data row with a
  missing or an extra cell; a duplicate `rule_id`; a cited test that does not exist; a cited test that
  fails; a cited test the runner reports as skipped; a `package` outside the target list; and no manifest at
  all (drive that one through the gate itself to see the required-step promotion turn `SKIP` into `FAIL`).
- Same host-independence rules as the rest of the harness suite: stdlib only, a stub tool on a pinned
  `PATH`, the gate's own root override so the shipped script is what the cases exercise.
- The mutation that proves the check belongs to the **input** as much as to the script: mutate the manifest
  (drop a test name, add a duplicate id) and the same check must go red. A checker whose rules are only
  proven against a script mutation has not been proven against the artifact it reads.
