# Phase 1 — branch and dispatch

0. Read the contract before anything else: every "Done when" clause and negative control in the goal
   file is binding, the accepted design doc owns the mechanism (do not reopen a decided dependency),
   and the shipped predecessor's completion record tells you what already exists, its residual limits,
   and which behaviours are deliberate non-goals.
1. `git fetch origin --prune`, fast-forward `main`, branch `feat/<kebab-outcome>` **from
   `origin/main`**, never from a stale local main. Report the base SHA every time.
2. Record the baseline before dispatching: `worktree-scope.py snapshot --repo <path> --label <goal>`.
   Report the count of pre-existing dirty paths in the dispatch line — they are not part of this
   increment. Refuse to dispatch on a dirty submodule or nested repository; resolve it first.
3. Dispatch one implementation run carrying the goal file, the repo's contract docs, the most recent
   comparable increment as the shape reference, the exact gate commands, and "do not commit/push".
   Use `scripts/gdd.py stage` so prompt, run name and ledger row come from one template.

## Dispatch tooling

```bash
scripts/gdd.py stage --repo <path> --goal <id> --stage <implement|simplify|apply|review|fix> \
  [--findings FILE] [--base SHA] [--launcher CMD] [--dry-run] [--wait]
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
- `references/bot-review-loop.md` — request/read/resolve cycle for an external review bot, marker
  shape, thread ids, infra vs real CI failure.
- `references/pr-body.md` — the PR body shape for a goal increment (evidence table, non-adoptions,
  clause→evidence mapping).
- `references/evidence-fairness.md` — making a "cheaper/faster" claim survive review.
- `references/profiles/_template.md` — per-repo profile template.
- `scripts/` — `gdd.py` (dispatch), `delivery-state.py` (ledger/resume), `pr-merge-check.py`
  (merge gate), `watch-pr-checks.sh` (bounded CI poller with infra-only rerun),
  `adapters/omp-run.sh` (reference tmux launcher), `adapters/events-writer.py` (bounded NDJSON
  writer the launcher copies into each run), `tests/run-gdd-selftest.sh`.
