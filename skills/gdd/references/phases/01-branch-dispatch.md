# Phase 1 — branch and dispatch

0. Read the contract before anything else: every "Done when" clause and negative control in the goal
   file is binding, the accepted design doc owns the mechanism (do not reopen a decided dependency),
   and the shipped predecessor's completion record tells you what already exists, its residual limits,
   and which behaviours are deliberate non-goals.
1. `git fetch origin --prune`, fast-forward `main`, branch `feat/<kebab-outcome>` **from
   `origin/main`**, never from a stale local main. Report the base SHA every time.
2. Resolve the scope tool with `uv run scripts/gdd.py scope`. Record the baseline before dispatching
   with `uv run "<scope-tool>" snapshot --repo <path> --label <goal>`.
   Report the count of pre-existing dirty paths in the dispatch line — they are not part of this
   increment. Refuse to dispatch on a dirty submodule or nested repository; resolve it first.
3. Dispatch one implementation run carrying the goal file, the repo's contract docs, the most recent
   comparable increment as the shape reference, the gates as one runnable command with an explicit
   working directory when the repo supports it, and no push. The contract's accepted plan is reused
   by path, not replanned. The `implement` template may delegate its loop to a runtime-offered
   `ce-work mode:return-to-caller` with an explicit plan path or bounded statement, the verbatim gate
   command and its working directory in separate caller context, and native execution or an
   operator-authorized route; its unit commits and a mid-loop simplification on this branch are
   accepted. Decide that eligibility before invoking: a missing or mismatched capability means the
   template's own loop, never an install, and after an invocation there is no fallback. The stage
   verifies the recorded goal branch, descent from the recorded base, scope across every commit and
   uncommitted path, and a complete summary with a recovery pointer. After an invocation, any failed
   check stops the stage with the state and the original snapshot left for the operator — no inline
   retry, resume or fallback. Neither the delegation nor its simplification decides phase 3: the
   simplify preflight still runs on the whole increment. Use `uv run scripts/gdd.py stage` so prompt,
   run name and ledger row come from one template, and settle the goal's run plan once before the
   first dispatch (`gdd.py setup`; roles, budgets and owner notes — see [Run plan](#run-plan)).

## Run plan

Before the first dispatch, run `uv run scripts/gdd.py setup --repo <path> --goal <id> [--plan-file <json>]`.
Ask the owner once, in one round, only for what `GDD_RUN_PLAN_DEFAULTS` does not give:
- the role map per agent stage: route (`agent`), `model`, `thinking`, `max_time` — ask only for fields the chosen
  route carries (list below);
- budgets: `rounds` per stage, plan-wide `max_time`, optional `token_cap`;
- `notes`.

Do not re-ask mid-run. Change the plan only on the owner's request, by re-running setup. Setup validates the plan
and names the offending key: `max_time` accepts the launcher's duration grammar (`90`, `90s`, `0.5h`), rounds must
be a positive integer or null (null means the default 2x), `token_cap` a non-negative integer or null, and
`agent`/`model`/`thinking` must not contain whitespace or `=` so the completion note stays parseable.

`gdd.py stage` resolves each field in this order: flag, role, environment, default; for max time the order is
flag, `roles.<stage>.max_time`, `budgets.max_time`, `GDD_MAX_TIME`, default. It appends the notes to every prompt
under `## Owner notes (run plan)`. It refuses past a stage's round cap or the plan's `token_cap`; `--over-budget`
overrides for one dispatch.

Token accounting reads each dispatched run's launcher `state.json` by the `run=<name>` its dispatch row records,
so detached, failed and interrupted attempts count too; a running, missing or malformed run state and a pre-plan
legacy row are listed as `unknown` and never summed. A completion note records the launcher-reported
route/model/thinking when the state carries them, else the requested value as `req:<value>`, else `default`.
`gdd.py status` prints the plan, the goal-wide known/unknown total beside the cap, and per-stage usage; with no
plan file it prints the legacy ledger view unchanged.

Roles fields per route: `agent` (the route selector) and `max_time` are accepted by every bundled route;
`model` and `thinking` by claude, codex, copilot, omo, omp and pi; opencode takes `thinking` only together with
`model`; dsh rejects both. Setup does not resolve the route, so a field the route cannot carry is refused by the
launcher at dispatch.

## Dispatch tooling

```text
uv run scripts/gdd.py stage --repo <path> --goal <id> --stage <stage> [--findings FILE] [--base SHA] [--launcher CMD] [--dry-run] [--wait]
```

Renders the stage prompt from `references/stage-templates/<stage>.md`, refuses to ship an unresolved
placeholder, refuses a second run in the same worktree, launches through the configured launcher, and
records the ledger row only after the launch actually started. Templates are the single source of
prompt text — never keep prompt copies elsewhere.

**A dispatch tool is only proven by dispatching.** A `--dry-run` self-test passes while the launch
path crashes on a typo, so any tool that starts runs needs (a) a hermetic launch test with a fake
launcher on `PATH` that writes a finished `state.json`, (b) a mutation check — revert each fix and
confirm the suite goes red — and (c) one real stage run before the pipeline depends on it. Expect the
first real uses to surface four or five defects (state that lies after a failure, a merge check that
returns green for an already-merged PR, a contract file that moved into the archive); fix them in
batched rounds rather than hand-patching the tool mid-run, and never let the operator's workaround
become the documented interface.

Delivery-specific transport rules: one headless run per stage = fresh context; never resume a previous
increment; parallel increments need `git worktree add` per branch; a fresh worktree has no build
outputs, so run the repo's build before any gate that reads compiled assemblies; never run two heavy
builds at once on a host sized for one — that is an OOM kill of whichever run loses, not a code
failure. Launcher contract, artifacts, recovery and liveness: [`references/transport.md`](../transport.md).

## Pitfalls this phase answers

- **`exit -9` is an OOM kill, not a bug.** The partial tree is usually salvageable — inspect it and
  dispatch a finish/verify instead of redoing the increment.

## Support files

- `references/stage-templates/` — stage prompts rendered by `gdd.py`; the only copy of prompt text.
- `references/phase-prompts.md` — the variable table for those templates (no prompt bodies).
- `references/transport.md` — launcher contract, artifacts, recovery, liveness.
- `references/bot-review-loop.md` — model-pinned machine-review invocation, full report/hash
  evidence, comment readback, finding dispositions, thread ids, infra vs real CI failure.
- `references/pr-body.md` — the PR body shape for a goal increment (evidence table, non-adoptions,
  clause→evidence mapping).
- `references/evidence-fairness.md` — making a "cheaper/faster" claim survive review.
- `references/profiles/_template.md` — per-repo profile template.
- `scripts/` — `gdd.py` (dispatch), `delivery-state.py` (ledger/resume), `pr-merge-check.py`
  (merge gate), `review-evidence.py` (full report evidence generator), `watch-pr-checks.py`
  (bounded CI poller with infra-only rerun),
  `agent_run.py` (bundled cross-platform headless runner, one for every agent CLI),
  `adapters/paseo-run.py` (opt-in native Paseo launcher), `tests/test_gdd.py` (dispatch and ledger),
  `tests/test_agent_run.py` (the runner suite that runs on any platform),
  `tests/test_watch_pr_checks.py` (the CI watcher's state machine, against a scripted `gh`).
