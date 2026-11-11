---
name: goal-driven-delivery
description: >-
  Land a written, machine-checkable increment in a repo end to end — one goal contract, one fresh
  authoring-agent run per stage, gates the operator re-runs, a scripted merge gate, and a durable stage
  ledger so a later session can resume in three commands. Use when an increment is delegated end to
  end, including the merge. Do not use for one-line fixes, exploration with no acceptance criteria, or
  work no machine can check (that is a conversation, not a delivery).
metadata:
  version: "0.1.35"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "goal contract → agent-authored stages → operator-run gates → scripted merge gate → resumable ledger; ships `gdd.py`, `delivery-state.py`, `pr-merge-check.py`"
  summary_zh: "目标契约 → agent 分阶段产出 → operator 验收 → 脚本化合并门禁 → 可续跑账本；随附 `gdd.py`、`delivery-state.py`、`pr-merge-check.py`"
  kind: "controller"
  produces: "chain-plan"
---

# Goal-driven delivery

One written increment (a goal), authored by a coding agent, verified and landed by the operator, with
the loop running end to end and no per-step approval. **Done** is merged *and* the next goal branched
off the merged head — an open PR is not done.

## When to Use

- "Start the next goal", "run the goal-driven flow", "finish this the usual way".
- 中文同义说法同样触发：`开始下一个 goal`、`推进 goal driven 流程`、`按老流程把这个做完`。
- Any multi-hour repo increment: a feature, a research-feasibility study, a migration, a docs
  rewrite — anything with a written completion contract and machine-checkable gates.
- A repo where the operator delegates end to end, including the merge.

Not for: one-line fixes, exploratory poking with no acceptance criteria, or work whose result no
machine can check.

## Stage order — fixed, no skipping

```
contract → implement → verify → simplify-report → apply → code-review-report → fix
        → gates → PR → babysit → merge → reset
```

Both two-phase steps are mandatory: an unapplied report or an unfixed review does not close a stage.
Caps: `implement` 2 recovery attempts, `simplify` 2 rounds, `review→fix` 2 rounds. On a third round,
stop and report — do not burn budget in silence.

## Roles — authoring vs inspection

- **The agent authors**: product code, tests, docs, evidence records, applying simplify/review fixes,
  re-running measurements. Dispatch it; never type it yourself, not even a two-line fix.
- **The operator inspects**: reading diffs, running gates read-only, grading findings, deciding to
  merge, and the mechanical git work (commit, push, PR, merge, cleanup).
- Why: a hand-edit from the wrong surface is an unaccounted write — the diff can no longer be
  attributed to the agent that owns the code, and the next review cannot reason about it.

## Phase table — route, then read the detail

| Phase | Produces | Rules that must not be missed | Detail |
|---|---|---|---|
| 0 contract | a dispatchable goal contract | all six clauses: observable pass condition, judging artifact, failure control, out of scope, evidence plan, mergeable alone; one goal ≈ one run ≈ one PR; fix the contract, never dispatch and hope | [`references/phases/00-contract.md`](references/phases/00-contract.md) |
| 1 branch + dispatch | baseline snapshot and one implementation run | branch from `origin/main` and report the base SHA; report pre-existing dirty paths; `gdd.py stage` renders prompt, run name and ledger row from one template | [`references/phases/01-branch-dispatch.md`](references/phases/01-branch-dispatch.md) |
| 2 verify | gate evidence and a clause→test map | exit 0 means the process ended, not the phase finished; re-run gates on the FINAL tree; a proof test must fail when the feature is deleted; a weak proof test is its own increment | [`references/phases/02-verify.md`](references/phases/02-verify.md) |
| 3 simplify → apply | accepted fixes | report only, never silent apply; name rejected numbers in the apply prompt; a dead-code finding needs mechanical evidence; re-derive changed counts from the tree | [`references/phases/03-simplify-apply.md`](references/phases/03-simplify-apply.md) |
| 4 review → fix | per-finding fixes | commit stage output before the next stage; reproduce every finding; classify regression vs pre-existing; a third same-class dispatch changes the mechanism | [`references/phases/04-review-fix.md`](references/phases/04-review-fix.md) |
| 5 gates → commit → PR | a sealed increment and its PR | `overlapping_paths` stops the commit; `worktree-scope.py verify` after committing; prove the branch is not behind main; every number is re-derived on the final tree | [`references/phases/05-gates-pr.md`](references/phases/05-gates-pr.md) |
| 6 merge | a merge verdict, then the next branch | `--verified-head` is the SHA the gates ran on; bot marker `status: completed` with `commit_sha` matching the SAME head; no merge without the script's verdict | [`references/phases/06-merge.md`](references/phases/06-merge.md) |
| 7 ledger | one ledger row per stage | the operator writes it, never the agent; resume with `show` + `git status` + `git log origin/main..HEAD`; mid-flight status comes from live state | [`references/phases/07-ledger.md`](references/phases/07-ledger.md) |
| 8 reset | a fresh base for the next goal | fresh run, never a resumed session; delete merged branches; fork from freshly fetched `origin/main`; report the base SHA | [`references/phases/07-ledger.md`](references/phases/07-ledger.md) |

## Platform-significant increments

When the repo ships on more than one OS, a green local run is not evidence. Fixtures, path literals,
goldens, signals and mode bits each carry a platform assumption; read
[`references/cross-platform-increments.md`](references/cross-platform-increments.md) before writing the
verification plan, and require the matrix job to print the failing test's own output.

## When a run dies or lies

Read [`references/run-failure-modes.md`](references/run-failure-modes.md) before adding a selftest case,
writing a verification plan, or believing a run's report of itself — a test can kill the process under
test, a stubbed test can pass for the wrong reason, a crashed run blocks the next stage, and an exit code
can disagree with the artifact it produced.

## Stop conditions — when to stop and ask

- Red line touched: destructive/irreversible action, production, credentials, public release, or
  anything affecting a third party. Report impact + rollback + the exact action, then wait.
- Scope drift or write overlap: a non-empty `overlapping_paths`, sealed-scope drift after commit, or
  work outside the contract stops the loop; the operator decides which writer owns the path.
- Two attempts in one stage with no convergence (`BLOCKED:no_progress`): stop, keep the evidence,
  present the choice (different model / narrower contract / abandon).
- Unfair evidence: a "faster/cheaper" claim that does not survive
  [`references/evidence-fairness.md`](references/evidence-fairness.md) is not accepted as an outcome.
- The contract itself is wrong (ambiguous or contradictory requirements discovered mid-flight): stop,
  amend it, then continue. Never ask an agent to satisfy an impossible clause.

## Configuration

| Variable | Resolves | Default |
|---|---|---|
| `GDD_STATE_FILE` | ledger path | `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/ledger.tsv` |
| `GDD_TASK_ROOT` | task/state root | `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/tasks` |
| `GDD_RUN_ROOT` | launcher run root | `${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs` |
| `GDD_LAUNCHER` | launcher command | the bundled `scripts/adapters/omp-run.sh` |
| `GDD_TEMPLATES` | stage-template root | the bundled `references/stage-templates` |
| `GDD_GOAL_GLOB` | goal-contract glob | `docs/goals/*<goal>*.md` |

Resolution order and the config-file path are defined once in
[skill-porting-and-publishing § Configuration](../skill-porting-and-publishing/SKILL.md#configuration-is-a-gate-not-advice).
`gdd.py` implements it through the vendored `scripts/skill_config.py`; the config-file keys are the
six names in the table, for example:

```yaml
# $XDG_CONFIG_HOME/goal-driven-delivery/config.yaml
GDD_STATE_FILE: /srv/state/gdd/ledger.tsv
GDD_TASK_ROOT: /srv/state/gdd/tasks
```

Nothing about one install lives in the protocol: a profile may point at its own files, but no path is
inlined.
