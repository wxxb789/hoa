---
name: hermes-agent-workflow-harness
description: Use when auditing or building agent workflow harnesses.
version: "0.1.1"
author: Zoe
license: MIT
metadata:
  version: "0.1.1"
  areas: "software-development"
  targets: "runtime-agnostic"
  hermes:
    tags: ["harness", "agent-workflow", "gates", "evidence", "evaluation"]
    related_skills: ["harness-engineering", "agent-operating-contract-evolution", "kanban-workflows"]
---

# Agent Workflow Harness

A coding-agent harness is the layer that wraps an agent doing repo work: command/prompt contracts,
artifact schemas, deterministic gate scripts, evidence receipts, optional evaluation. Its failure
mode is not a stalled cron job (that is `harness-engineering`'s world) but an agent that **says** it
is done. This skill covers judging such a harness from outside and building one to this owner's
standards.

## When to Use

- 有人丢来一个 harness 仓库（Superpowers / OpenSpec / HelixHarness 这类）问：它做了什么、支持哪些
  agent、我能借鉴什么
- 要给 agent 工作流加「完成 / 评审通过 / 范围没漂」的判定，而不只是加更多 prompt
- 一个仓的 agent 流程需要跨 runtime（多个 CLI / 多个 agent 产品）复用时

Not for: scheduled operational scripts and checkers (`harness-engineering`), agent identity/contract
files (`agent-operating-contract-evolution`), or application code.

## Always-on rules

1. **A self-report is not evidence.** Every done / reviewed / scope-unchanged claim needs a value a
   script recomputes. Seal the *worktree increment*, not the contract: at review time record the
   changed paths plus a content digest per path, and re-verify that digest before merge/archive.
   Trace the contract (goal/spec/tasks) by git commit ref only. Do **not** hash contract text: a
   contract hash makes every later edit invalidate all in-flight bindings, so drift reports become
   routine and a repair ritual (re-key, re-bind, re-seal) grows around them for no gain.
2. **Separate pre-existing dirt from this task's diff.** At task start record `HEAD` plus a manifest
   of already-dirty paths into private gitignored state; review excludes unchanged pre-existing paths
   automatically and stops only when the same path was dirty *and* modified. Never ask the owner to
   clean/stash/commit before starting.
3. **Two review axes, never merged.** Standards (repo rules + smell baseline) and Spec (AC by AC) run
   as isolated parallel reviewers with separate verdicts; any later code change voids APPROVE.
4. **Instruction density must be paid for in determinism.** Judge a harness by tests-per-rule, not
   prose quality. Contract sets in the tens of thousands of lines survive only on a large test suite
   plus one gate script as the single source of truth. Adding a rule without a gate is how harnesses
   drift; a rule the gate cannot check should not be written. How to write such a gate — deterministic
   input set, inline exception markers with a mandatory reason, a self-test that proves both directions,
   and a failure line that carries the fix — is [`references/deterministic-convention-gates.md`](references/deterministic-convention-gates.md).
5. **Port by capability matrix, fail closed.** Runtime differences live in a manifest declaring each
   capability `native | emulated | unsupported` plus a logical→native tool mapping; shared core keeps
   no `if <platform>`. An unknown runtime is a hard failure, never a fallback to the tested one.
6. **Do not port a workflow harness onto a runtime lacking subagent spawn+wait** (count,
   dependencies, role isolation, failure propagation). Parallel scan DAGs and isolated review axes
   degrade to sequential prose — the appearance of gates without the substance.
7. **Deliverable shape for this owner**: depth to `~/claw/tasks/<date>/<topic>/`, chat carries
   conclusions only; label every claim **Fact / Inference / Judgment**; end with borrow tiers
   (P0 now / P1 with governance / explicit no-borrow list) and one concrete next step. When the
   deliverable is a change to the library itself, land it constraint-first: the machine-checkable rule
   and its negative test, then the cheapest rule that pays for itself, then the structural split — a
   split landed before its constraint grows back into one file within a month.
8. **Split the harness the way this owner asks for it: mechanism skills plus one routing controller,
   and gate only the expensive stages.** Never keep growing a single pipeline skill — each added rule
   makes it harder to reuse and easier to ignore. The controller answers "which skills run, and what
   must be true between them" and owns nothing else; each mechanism owns one verb and one artifact.
   Two refinements that survive review: (a) the controller must be *code* — a table or a validator
   subcommand — because a prose router reads the same state files as the method and gets fused with it
   under context pressure; (b) "heavy" is two axes, not one: cheap determinism (hash compare, state
   verdict, merge gate) belongs in the default path, and only cost-heavy stages (isolated parallel
   reviewers, multi-round clarification) go behind an explicit tier. Nobody opts in to a gate while
   rushing, which is exactly when the gate was needed.

## Procedure (studying an external harness)

1. Shallow-clone into scratch, never into `~/repos`; commit count comes from the host page, not the
   shallow log.
2. Size-and-role inventory per directory before reading prose; a directory dwarfing everything else
   is usually a vendor toolchain and stays out of the verdict.
3. Count tests before trusting claims.
4. Read in order: entry commands → one stage body → context-loading protocol → tool-semantics map →
   host manifest → gate script's subcommand list. Stop when the contract is clear.
5. Answer "supports agent X" from manifests, not the feature list; absence plus "unknown host fails
   closed" is the answer.
6. Full recipe, portability checklist, and pattern catalog:
   - `references/external-harness-audit.md`
   - `references/borrowable-patterns.md`
   - `references/harness-skill-decomposition.md` (splitting a pipeline into composable skills)

## Pitfalls

- **A dispatch brief that names an artifact the base commit lacks gets that artifact invented.** Before
  a brief names a repo path, verify it (`git show origin/main:<path>`, `git ls-tree`); otherwise state
  the contract the artifact must satisfy and declare creation out of scope. A capable agent treats a
  missing named file as work to do, authors a plausible placeholder, discloses it as a "deviation", and
  ships it — disclosure does not make an unowned duplicate acceptable. On acceptance, diff delivered
  paths against the paths the brief named: the extra one is fabricated content. Add a concurrency guard
  to every brief as well: assert a clean tree and a branch the run created itself before editing.
  A second lane in the same checkout switches branches under the first one mid-run, so "the last
  commit" can belong to work this run never did — read `git log --oneline origin/main..HEAD` on the
  named branch, not on whatever `HEAD` happens to point at.
- **Stars measure interest, not adoption.** Before writing "how they landed this in a team", look for
  rollout evidence (teams, repos, a metric delta). Mechanism plus marketing is design intent — label
  it that way instead of presenting an unsourced case study.
- **`lite_*` / `-lite` failure codes mean the public release is a trim of an internal one.** Treat the
  documented capability list as an upper bound and re-verify shipped behavior before promising it.
- **A workflow harness is not the thing to port; the gate script is.** Port the deterministic layer
  (validator subcommands, receipts, scope sealing) first, the prose second.
- **Do not recommend the eval platform to a team without a maintainer role.** Case calibration plus
  worker pools plus judging is maintainer-scale cost; the repo's own test suite (F2P/P2P) is the
  cheap honest substitute.
- **Never let an agent append to its own knowledge base freely.** Knowledge writes need a path
  whitelist sealed by an explicit confirmation, plus a scope-drift block.
- **Splitting a pipeline into skills creates schema drift that no single owner watches.** A cross-skill
  artifact (goal/contract file, ledger row, receipt) must have its shape declared once and its producer
  named; check the contract graph in CI. Unified version bumps catch version mismatch, never "skill A
  expects a field skill B stopped writing".
- **A classification the author may omit is not a constraint.** A contract check that validates only the
  skills declaring `kind` is opted out of by silence: the all-in-one skill declares nothing and passes,
  and an 800-line file labelled `entry` satisfies every rule that constrains only `controller`.
  Require `kind` on **every** skill: a curated `required_kind` list is the same escape hatch one level
  up — it was tried, and the skills outside the list stayed unchecked while its presence made the graph
  look enforced. Enforce the controller's file-length cap in the same check; both are static
  comparisons, so both belong in CI rather than in a review habit. State the residual honestly: a skill
  that is labelled and still bloated passes, and that is a review finding, not something a linter sees.
- **A per-PR patch bump is unsafe under parallel merges.** Two branches bump from the same base, both
  satisfy "exactly one patch above `origin/main`", and the second merge's release job dies on a tag
  collision while `VERSION` sits at a duplicate. Re-run the bump check after every rebase (that is the
  only moment the branch learns about a sibling merge), make the release step fail loudly instead of
  retagging, and treat the next merged PR's bump as the repair — never force the tag to make CI green.
- **A rule with no failing case behind it belongs in references, not in the protocol body.** Ask "what
  did this rule prevent?" before adding it; if the answer is a plausible worry rather than a defect or
  an eval case, it is a note. This is the only standing defence against a 10k-line instruction set.
- **A gate that reports a name or a count instead of the reason is a round-trip generator.** `pkg/Test:
  failed` with no message, `3 violations`, `head mismatch` — each one forces the next reader to reproduce
  what the gate already knew. Emit the failing item's own output tail-bounded, and on a multi-OS matrix
  assume the reader cannot re-run that platform at all. Fix the reporting first; it pays back on failures
  this increment did not cause.
- **An exception mechanism that lives in a central ignore file excuses a class, not a case.** Inline
  markers with a mandatory reason keep the justification next to the code it covers and are re-read by
  whoever edits that line; an allowlist keyed on paths or rule ids drifts away and quietly makes the gate
  decorative. Pair it with a self-test that puts a justified exception beside an unjustified violation.

- **An artifact edge is paper until a consumer reads it.** `produces: spec` on one skill and
  `consumes: spec` on another keep the graph green and prove only that the metadata agrees with itself.
  A real edge needs both halves: the producer names where the artifact is written (path plus the
  config resolution chain) and the consumer's body contains the step that opens that file. Check by
  grepping the consumer for the artifact's location, not by reading the graph — a downstream skill that
  actually reads a *plan* while declaring `consumes: spec` is a broken edge with a passing check.
- **A clarification round that carries the whole frontier degenerates into blanket approval.** With
  8–15 open decisions, each carrying facts, options and a recommendation, the operator's rational move
  is to approve every recommendation — the protocol then defines the exact failure it induces. Group a
  round by one concern (usually a concept the protocol already defines and then never uses), cap the
  round, and order the overflow by which decision blocks scope or the test seam. Require the
  confirmation summary to quote the operator's own answers, to list every option the agent dropped and
  the fact that dropped it, and to accept "searched X, found nothing" as evidence — otherwise greenfield
  work stalls on a rule written for brownfield. The repository shows what the system does today; whether
  that behaviour stays is always the operator's choice, never a lookup the repo already answered.
