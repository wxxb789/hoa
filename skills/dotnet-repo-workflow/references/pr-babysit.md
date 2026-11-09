# PR babysit without a skill loader

Some harnesses ship a PR-babysit skill with its own state engine (`pr-snapshot`, a Python file with no
extension, in that skill's `scripts/`). When the orchestrator's profile disables that skill, drive the
helper directly — its output is the only source of truth for PR state.

## Session shape

1. **The first snapshot mints the invocation.** Keep the state dir inside the task dir so the proof
   survives the session:

   ```bash
   python3 <ce-babysit-pr>/scripts/pr-snapshot snapshot --pr <N> --repo <owner/repo> \
     --state-dir <task>/state --start-invocation
   ```

   Record `invocation_id`, `invocation_started_at`, `invocation_budget_seconds`; every later
   `snapshot`, `watch`, and `mark` must repeat all three or the helper rejects the call.

2. **One watcher, backgrounded with a wake pattern.** Do not hand-roll a poll loop in the agent:

   ```bash
   python3 <ce-babysit-pr>/scripts/pr-snapshot watch --pr <N> --repo <owner/repo> \
     --state-dir <DIR> --invocation-id <id> --session-started-at <ts> \
     --invocation-budget-seconds <budget> --interval 120
   ```

   Launch it as a background job that notifies on a `BABYSIT_WAKE` line. It prints one line and exits;
   every wake is one tick. Never run two watchers on one PR.

3. **Tick order** (fresh snapshot first): terminal check → capture head SHA → non-thread feedback and
   threads → CI failures on the current head → branch currency. Feedback outranks CI; a stale head
   cancels the CI findings from that snapshot.

## Classifying the two things that always appear

- **A review bot's status comment** ("Review: 🔄 Running", machine-readable `has_any_findings: null`)
  is status noise, not feedback. Silencing it is the documented resolver output, so skip the dispatch
  and mark it:
  `pr-snapshot mark --pr <N> --repo <owner/repo> --state-dir ... --comment <id> --disposition dispatched`.
- **A completed review whose marker carries an older `commit_sha`** is stale, not clean. A push does
  not trigger a re-review: request one and match the marker's `commit_sha` to the new head before
  counting it.

## Ending the babysit

The loop ends on a terminal PR state (`MERGED` / `CLOSED`) or when the merge gate itself says
`MERGE-OK` — never on "CI is green", which is not merge permission.
